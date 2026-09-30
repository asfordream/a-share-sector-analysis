#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""增量补全 volGrade：只补当前文件里 volGrade 仍为空(或缺失)的个股，
不覆盖已有值（避免 swing.py 整文件重写时把已成功个股冲掉）。
用法: python3 scripts/swing_fill.py <板块1> <板块2> ... [轮数=6]
"""
import json, os, subprocess, sys, time
from datetime import datetime, time as dtime

TODAY = datetime.now().strftime("%Y-%m-%d")
_NOW = datetime.now().time()
INTRADAY = dtime(9, 15) <= _NOW < dtime(15, 5)

CLI = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sector-webapp/westock_cli.js")
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
NAMES = ["A股创新药", "算力", "半导体", "存储", "人形机器人", "光通信", "CPO",
         "PCB", "商业航天", "电网设备", "AI应用"]
ROUNDS = int(sys.argv[-1]) if sys.argv[-1].isdigit() else 6


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
    pairs = [(r.get("date"), num(r.get("volume"))) for r in rows]
    pairs = [(d, v) for d, v in pairs if v is not None and v > 0]
    if len(pairs) < 6:
        return None, None, "量能数据不足"
    intraday_bar = bool(INTRADAY and pairs[-1][0] == TODAY)
    cvols = [v for _, v in (pairs[:-1] if intraday_bar else pairs)]
    if len(cvols) < 6:
        return None, None, "量能数据不足"
    v5 = sum(cvols[-5:]) / 5.0
    v20 = sum(cvols[-20:]) / min(20, len(cvols))
    if v20 <= 0 or v5 <= 0:
        return None, None, "量能为0"
    shrink = v5 / v20
    if intraday_bar:
        if vol_ratio and vol_ratio > 0:
            expand, esrc = float(vol_ratio), "量比"
        else:
            expand, esrc = cvols[-1] / v5, "上一完整日"
        if dtime(9, 15) <= _NOW < dtime(10, 15):
            expand = min(expand, 30)
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
    s = max(0, min(100, s + e))
    grade = "强" if s >= 75 else ("中" if s >= 40 else "弱")
    return s, grade, f"缩量比{shrink:.2f}/放量比{expand:.2f}({esrc})"


def missing(d):
    # 仅补 volGrade 为空(None/None 字符串，即无 K线/量能数据) 或 swingLow 缺失的个股；
    # 已评分「弱」的个股已有真实量能数据，不应重抓（其本来就因量能弱被候选漏斗剔除）。
    return [u for u in d["universe"]
            if u.get("volGrade") in (None, "") or u.get("volGrade") == "None"
            or u.get("swingLow") is None]


def main():
    names = [n for n in (sys.argv[1:] if len(sys.argv) > 1 and not sys.argv[-1].isdigit() else sys.argv[1:]) if n in NAMES] or NAMES
    for nm in names:
        p = f"{OUT}/{nm}.json"
        if not os.path.exists(p):
            continue
        for rnd in range(ROUNDS):
            d = json.load(open(p, encoding="utf-8"))
            todo = missing(d)
            if not todo:
                break
            sys.stderr.write(f"[{nm}] round{rnd+1}: 待补 {len(todo)}/{len(d['universe'])}\n")
            codes = [u["code"] for u in todo]
            bars = {}
            for i in range(0, len(codes), 14):
                ch = codes[i:i + 14]
                for r in parse_table(run(["kline", ",".join(ch), "--period", "day", "--limit", "40", "--fq", "qfq"])):
                    s = r.get("symbol")
                    if s:
                        bars.setdefault(s, []).append(r)
                time.sleep(0.4)
            filled = 0
            for u in d["universe"]:
                if u.get("volGrade") not in (None, "") and u.get("volGrade") != "None" and u.get("swingLow") is not None:
                    continue
                rows = bars.get(u["code"], [])
                rows = sorted((r for r in rows if r.get("date")), key=lambda x: x["date"])
                lows = [num(r.get("low")) for r in rows if num(r.get("low"))]
                highs = [num(r.get("high")) for r in rows if num(r.get("high"))]
                vs, vg, vd = vol_score(rows, u.get("volRatio"))
                if vs is not None and vg:
                    u["volScore"], u["volGrade"], u["volDetail"] = vs, vg, vd
                if lows and highs:
                    lo, hi = min(lows), max(highs)
                    px = u["price"]
                    u["swingLow"] = round(lo, 2)
                    u["swingLowDate"] = next((r["date"] for r in rows if num(r.get("low")) == lo), None)
                    u["swingHigh"] = round(hi, 2)
                    u["reboundPct"] = round((px - lo) / lo * 100, 2) if px else None
                    u["ddFromHigh"] = round((px - hi) / hi * 100, 2) if px else None
                    filled += 1
            json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            if not missing(d):
                break
        d = json.load(open(p, encoding="utf-8"))
        ok = sum(1 for u in d["universe"] if u.get("volGrade") not in (None, "", "弱") and u.get("swingLow") is not None)
        sys.stderr.write(f"{nm}: 最终 {ok}/{len(d['universe'])}\n")


if __name__ == "__main__":
    main()
