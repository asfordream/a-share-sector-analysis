#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""为每个板块 universe 拉 40 日K线，计算 swing low(失效价) / 反弹幅度 / 距高点回撤"""
import json, os, subprocess, sys, time
from datetime import datetime, time as dtime

TODAY = datetime.now().strftime("%Y-%m-%d")
_NOW = datetime.now().time()
# A股交易时段内（含集合竞价到收盘后 5 分钟缓冲）→ 当日 K 线 bar 为「未完成 bar」
INTRADAY = dtime(9, 15) <= _NOW < dtime(15, 5)


def _elapsed_trading_min(t=None):
    """已完成交易分钟数（09:30-11:30 + 13:00-15:00，共 240 分钟）"""
    t = t or _NOW
    m = t.hour * 60 + t.minute
    am_s, am_e, pm_s, pm_e = 9 * 60 + 30, 11 * 60 + 30, 13 * 60, 15 * 60
    el = 0
    el += max(0, min(m, am_e) - am_s)
    el += max(0, min(m, pm_e) - pm_s)
    return min(240, el)


ELAPSED_MIN = _elapsed_trading_min()

CLI = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sector-webapp/westock_cli.js")
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
NAMES = ["A股创新药", "算力", "半导体", "存储", "人形机器人", "光通信", "CPO",
         "PCB", "商业航天", "电网设备", "AI应用"]  # 2026-08-18 移除证券/电力/光模块、新增电网设备；2026-08-31 新增 AI应用；2026-09-04 移除宇树科技概念；2026-09-23 移除元件、新增 CPO


def run(args, retries=3):
    for i in range(retries):
        try:
            r = subprocess.run(["node", CLI] + args, capture_output=True, text=True, timeout=180)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout
        except Exception as e:
            sys.stderr.write(f"  ! {e}\n")
        time.sleep(2)
    return ""


def parse_table(text):
    lines = [l.strip() for l in text.splitlines() if l.strip().startswith("|")]
    if len(lines) < 3:
        return []
    hdr = [c.strip() for c in lines[0].strip("|").split("|")]
    out = []
    for l in lines[2:]:
        c = [x.strip() for x in l.strip("|").split("|")]
        if len(c) == len(hdr):
            out.append(dict(zip(hdr, c)))
    return out


def num(v, d=None):
    try:
        return float(v)
    except Exception:
        return d


def vol_score(rows, vol_ratio=None):
    """量能评分(0-100)=缩量回踩(50)+放量确认(50)。rows 需按 date 正序。
    缩量比 shrink=近5个完整交易日均量/20日均量；放量比 expand=当日量/近5日均量。

    ⚠️ 盘中口径修正（2026-08-13 加）：盘中运行时当日 bar 为未完成 bar，
    直接用 volume/v5 会把 expand 压到 0.1~0.5 → 量能几乎全判「弱」→ 候选归零
    （2026-08-12 已踩坑）。修正：
      1) 缩量比只用「已收盘的完整交易日」（剔除当日未完成 bar）；
      2) 放量比改用 quote 的 **量比 volume_ratio**（其定义=当日每分钟均量/过去5日每分钟均量，
         天然时间归一化），无量比则退回上一完整交易日；
      3) 开盘首 60 分钟量比系统性虚高（集合竞价前置放量）→ 放量分封顶 30，避免过度给分。
    分级：强>=75 / 中40-74 / 弱<40。"""
    pairs = [(r.get("date"), num(r.get("volume"))) for r in rows]
    pairs = [(d, v) for d, v in pairs if v is not None and v > 0]
    if len(pairs) < 6:
        return None, None, "量能数据不足"

    intraday_bar = bool(INTRADAY and pairs[-1][0] == TODAY)
    cvols = [v for _, v in (pairs[:-1] if intraday_bar else pairs)]   # 完整交易日量序列
    if len(cvols) < 6:
        return None, None, "量能数据不足"

    v5 = sum(cvols[-5:]) / 5.0
    v20 = sum(cvols[-20:]) / min(20, len(cvols))
    if v20 <= 0 or v5 <= 0:
        return None, None, "量能为0"
    shrink = v5 / v20

    cap_expand = None
    if intraday_bar:
        if vol_ratio and vol_ratio > 0:
            expand, esrc = float(vol_ratio), "量比"
        else:
            expand, esrc = cvols[-1] / v5, "上一完整日"
        if ELAPSED_MIN < 60:
            cap_expand = 30           # 开盘首小时放量分封顶
    else:
        expand, esrc = cvols[-1] / v5, "当日"

    s = 0
    if shrink <= 0.5:
        s += 50
    elif shrink <= 0.8:
        s += 30
    elif shrink <= 1.0:
        s += 15

    if expand >= 1.2:
        e = 50
    elif expand >= 1.0:
        e = 30
    elif expand >= 0.8:
        e = 15
    else:
        e = 0
    if cap_expand is not None:
        e = min(e, cap_expand)
    s = max(0, min(100, s + e))

    grade = "强" if s >= 75 else ("中" if s >= 40 else "弱")
    tag = f"·盘中{ELAPSED_MIN}分钟" if intraday_bar else ""
    return s, grade, f"缩量比{shrink:.2f}/放量比{expand:.2f}({esrc}){tag}"


for nm in (sys.argv[1:] or NAMES):
    p = f"{OUT}/{nm}.json"
    d = json.load(open(p, encoding="utf-8"))
    codes = [u["code"] for u in d["universe"]]
    bars = {}
    for i in range(0, len(codes), 14):
        ch = codes[i:i + 14]
        for r in parse_table(run(["kline", ",".join(ch), "--period", "day", "--limit", "40", "--fq", "qfq"])):
            s = r.get("symbol")
            if not s:
                continue
            bars.setdefault(s, []).append(r)
        time.sleep(0.4)

    hit = 0
    for u in d["universe"]:
        rows = bars.get(u["code"], [])
        rows = [r for r in rows if r.get("date")]
        rows.sort(key=lambda x: x["date"])
        lows = [num(r.get("low")) for r in rows if num(r.get("low"))]
        highs = [num(r.get("high")) for r in rows if num(r.get("high"))]
        vs, vg, vd = vol_score(rows, u.get("volRatio"))
        u["volScore"], u["volGrade"], u["volDetail"] = vs, vg, vd
        if not lows or not highs:
            u["swingLow"] = None
            u["swingLowDate"] = None
            u["reboundPct"] = None
            u["ddFromHigh"] = None
            continue
        lo = min(lows)
        hi = max(highs)
        lodate = next((r["date"] for r in rows if num(r.get("low")) == lo), None)
        px = u["price"]
        u["swingLow"] = round(lo, 2)
        u["swingLowDate"] = lodate
        u["swingHigh"] = round(hi, 2)
        u["reboundPct"] = round((px - lo) / lo * 100, 2) if px else None
        u["ddFromHigh"] = round((px - hi) / hi * 100, 2) if px else None
        hit += 1

    json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    sys.stderr.write(f"{nm}: swing {hit}/{len(d['universe'])}\n")
