#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A股板块候选跟踪表「信号有效性」回溯验证（2026-09-29 用户需求；独立任务，不入自动化）。

目的：验证跟踪表两类信号在历史数据上是否真正成立 —— 回抽确认(cands) / 主升浪买点区(mups)。

⚠️ 为什么要重做验证：跟踪表原「状态」列由 build_track_table._status() 按【当日快照价】机械判定
（现价≥目标1→已止盈 / 现价≤买点上沿→已触发 / 现价≤止损→已止损），**没有路径概念**：
既不记录「信号发出后是否曾触及止损」，也不区分「先止损还是先止盈」。
故「状态」列不能当成败依据 → 本脚本改用日K线做真正的事件研究。

方法论（Event Study）：
  1) 入场：信号日收盘价若落在买点区间内 → 以该收盘价入场；
     否则自信号日次日起，首个「日内触及买点区间」的交易日按区间挂单成交（价 = clamp(open, lo, hi)）；
     若某日**开盘即跌破买点下限** → 判「跳空破位，信号失效」不入场（挂在区间内的单不该成交）。
  2) 出场：自入场日次日起逐日推进 ——
     触及止损 → 成交价 min(open, stop)（跳空低开更差，贴合止损单实际）；
     触及目标1/目标2 → 按目标价成交（挂单止盈口径，不美化跳空高价）；
     同日既触止损又触目标 → 日内先后无法判定 → 保守计「止损(同日双向)」并单独披露。
  3) 数据边界：截止 2026-09-28（09-29 是未完成盘中 bar，已剔除；2026-09-25 中秋节休市无行情）。
  4) 未触及任何边界 → 「持有中」，按最新收盘价算浮动收益。

结果分类：T2 完全成功 / T1 成功 / SL 失败 / SL_AMBIG 失败(同日双向) /
         NO_ENTRY_NEVER 从未进入买点区 / NO_ENTRY_BREAK 跳空破位未入场 / OPEN 持有中

用法：
  python3 scripts/verify_signals.py --fetch        # 只拉/更新K线缓存
  python3 scripts/verify_signals.py                # 拉(如需)+模拟+统计 → data/_verify_result.json
  python3 scripts/verify_signals.py --refresh      # 强制重拉K线
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
XLSX = os.path.join(BASE, "A股板块候选跟踪表.xlsx")
CACHE = os.path.join(DATA, "_verify_kline_cache.json")
OUT = os.path.join(DATA, "_verify_result.json")
CLI = os.path.join(BASE, "sector-webapp", "westock_cli.js")
SHEETS = ["回抽确认", "主升浪买点区"]
START, END = "2026-08-01", "2026-09-28"
DATA_END = "2026-09-28"


# ---------- 基础工具 ----------
def pnum(v):
    """从 '109.97（破MA20离场）' / 'n/a' / 4.5 中取数值。"""
    if v is None:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", str(v).replace(",", ""))
    return float(m.group(0)) if m else None


def parse_buy(v):
    """'119.53~123.23' → (119.53, 123.23)"""
    m = re.match(r"\s*(-?\d+(?:\.\d+)?)\s*~\s*(-?\d+(?:\.\d+)?)", str(v))
    return (float(m.group(1)), float(m.group(2))) if m else (None, None)


def fdate(d):
    """'20260818' → '2026-08-18'"""
    d = str(d)
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}"


def run_cli(args, timeout=180, retries=3):
    for _ in range(retries):
        try:
            r = subprocess.run(["node", CLI] + args, capture_output=True,
                               text=True, timeout=timeout)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout
        except Exception as e:  # noqa: BLE001
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


def guess_prefix(code):
    c = str(code).strip()
    if c[:2].lower() in ("sh", "sz", "bj"):
        return c.lower()
    if c[:1] in ("6", "9"):
        return "sh" + c
    if c[:1] in ("0", "2", "3"):
        return "sz" + c
    if c[:1] in ("4", "8"):
        return "bj" + c
    return c


def build_code_map():
    """纯6位代码 → 带交易所前缀（优先取 data/*.json 的 universe，最准）。"""
    m = {}
    for f in glob.glob(os.path.join(DATA, "*.json")):
        if os.path.basename(f).startswith("_"):
            continue
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(d, dict):
            continue
        for u in (d.get("universe") or []):
            c = str(u.get("code") or "")
            if not c:
                continue
            key = c[2:] if c[:2].lower() in ("sh", "sz", "bj") else c
            m[key] = c.lower()
    return m


# ---------- 读跟踪表 ----------
def load_track():
    from openpyxl import load_workbook
    wb = load_workbook(XLSX)
    rows = []
    for sh in SHEETS:
        if sh not in wb.sheetnames:
            continue
        ws = wb[sh]
        for r in range(2, ws.max_row + 1):
            d = ws.cell(r, 1).value
            if d in (None, ""):
                continue
            buy = ws.cell(r, 11).value
            lo, hi = parse_buy(buy)
            rows.append({
                "sheet": sh, "date": str(d), "date_f": fdate(d),
                "sector": ws.cell(r, 2).value, "shape": ws.cell(r, 3).value,
                "sig": ws.cell(r, 4).value, "code": str(ws.cell(r, 5).value),
                "name": ws.cell(r, 6).value, "sig_price": pnum(ws.cell(r, 7).value),
                "distMa20": ws.cell(r, 8).value,
                "buy_lo": lo, "buy_hi": hi,
                "stop": pnum(ws.cell(r, 12).value), "t1": pnum(ws.cell(r, 13).value),
                "t2": pnum(ws.cell(r, 14).value), "hi52": pnum(ws.cell(r, 15).value),
                "sheet_status": ws.cell(r, 17).value,
            })
    return rows


# ---------- 拉K线 ----------
def fetch(bars_store, codes, refresh=False):
    done = {} if refresh else dict(bars_store)
    todo = [c for c in codes if c not in done or not done[c].get("bars")]
    if not todo:
        print(f"K线缓存已覆盖全部 {len(codes)} 只，跳过拉取")
        return done
    print(f"需拉取 {len(todo)} 只（共 {len(codes)}）…")
    miss = []
    for i in range(0, len(todo), 14):
        ch = todo[i:i + 14]
        out = run_cli(["kline", ",".join(ch), "--period", "day",
                       "--start", START, "--end", END, "--fq", "qfq"])
        got = set()
        for r in parse_table(out):
            s = str(r.get("symbol") or "").lower()
            if not s:
                continue
            got.add(s)
            bars = done.setdefault(s, {}).setdefault("bars", [])
            bars.append({
                "date": r.get("date"),
                "open": pnum(r.get("open")), "high": pnum(r.get("high")),
                "low": pnum(r.get("low")), "close": pnum(r.get("last")),
                "volume": pnum(r.get("volume")),
            })
        for c in ch:
            if c.lower() not in got:
                miss.append(c)
        print(f"  [{i // 14 + 1}/{(len(todo) + 13) // 14}] {len(ch)} 只 → 命中 {len(got)}")
        time.sleep(0.4)
    for k, v in done.items():
        bars = [b for b in v.get("bars", []) if b.get("date") and b.get("close") and b.get("high")]
        v["bars"] = sorted({b["date"]: b for b in bars}.values(), key=lambda x: x["date"])
    if miss:
        print(f"  ⚠️ 未返回数据的代码 {len(miss)} 只：{miss[:20]}")
    json.dump(done, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"缓存已写：{CACHE}（{len(done)} 只）")
    return done


# ---------- 单行模拟 ----------
def simulate(row, bars):
    """返回评价 dict。bars 按日期正序、已剔除非交易日与未完成 bar。"""
    lo, hi, stop, t1, t2 = row["buy_lo"], row["buy_hi"], row["stop"], row["t1"], row["t2"]
    res = {"entry": None, "entry_date": None, "entry_how": None, "exit": None,
           "exit_date": None, "exit_price": None, "result": None, "ret": None,
           "hold_days": None, "mfe": None, "mae": None, "note": ""}
    if not bars or lo is None or hi is None:
        res["result"] = "NO_DATA"
        return res
    by_date = {b["date"]: b for b in bars}
    sig_bar = by_date.get(row["date_f"])
    after = [b for b in bars if b["date"] > row["date_f"]]

    # --- 入场 ---
    if sig_bar and lo <= sig_bar["close"] <= hi:
        res.update(entry=sig_bar["close"], entry_date=sig_bar["date"], entry_how="信号日收盘")
        rest = after
    else:
        entry = None
        for b in after:
            o = b["open"]
            # 只有「开盘已跌破止损线」才算信号真正失效（破位）；开盘略低于买点下沿仍属可成交范围
            if o is not None and stop is not None and o < stop:
                res["result"] = "NO_ENTRY_BREAK"
                res["note"] = f"{b['date']} 开盘 {o:.2f} 已跌破止损线 {stop:.2f} → 破位失效，不入场"
                return res
            if b["low"] is not None and b["low"] <= hi:
                if o is None or o >= lo:
                    entry = (min(o if o is not None else hi, hi), b["date"], "区间挂单")
                else:
                    entry = (o, b["date"], "低开成交")  # 低于买点下沿但未破止损 → 低开给了更优买点
                break
        if entry is None:
            res["result"] = "NO_ENTRY_NEVER"
            res["note"] = f"至 {DATA_END} 价格从未回落进买点区间 {lo:.2f}~{hi:.2f}"
            return res
        res.update(entry=entry[0], entry_date=entry[1], entry_how=entry[2])
        rest = [b for b in bars if b["date"] > entry[1]]

    ent = res["entry"]
    # --- 出场 ---
    hi_px, lo_px = ent, ent
    for b in rest:
        o, h, l = b["open"], b["high"], b["low"]
        hi_px = max(hi_px, h if h is not None else ent)
        lo_px = min(lo_px, l if l is not None else ent)
        hit_sl = (o is not None and o <= stop) or (l is not None and l <= stop)
        hit_t1 = (o is not None and o >= t1) or (h is not None and h >= t1)
        hit_t2 = (o is not None and o >= t2) or (h is not None and h >= t2)
        if hit_sl and (hit_t1 or hit_t2):
            res.update(result="SL_AMBIG", exit="止损(同日双向)", exit_date=b["date"],
                       exit_price=min(o, stop) if o is not None else stop)
            break
        if hit_sl:
            res.update(result="SL", exit="止损", exit_date=b["date"],
                       exit_price=min(o, stop) if o is not None else stop)
            break
        if hit_t2:
            res.update(result="T2", exit="目标2", exit_date=b["date"], exit_price=t2)
            break
        if hit_t1:
            res.update(result="T1", exit="目标1", exit_date=b["date"], exit_price=t1)
            break
    # MFE / MAE（入场后到出场日或数据截止）
    res["mfe"] = round((hi_px / ent - 1) * 100, 2)
    res["mae"] = round((lo_px / ent - 1) * 100, 2)

    if res["result"] is None:
        last = bars[-1]
        res.update(result="OPEN", exit="持有中", exit_date=last["date"], exit_price=last["close"])
    if res["exit_price"] is not None and ent:
        res["ret"] = round((res["exit_price"] / ent - 1) * 100, 2)
    # 持有交易日数
    dates = [b["date"] for b in bars]
    try:
        res["hold_days"] = dates.index(res["exit_date"]) - dates.index(res["entry_date"])
    except ValueError:
        res["hold_days"] = None
    return res


# ---------- 统计 ----------
WIN = ("T2", "T1")
LOSE = ("SL", "SL_AMBIG")
LABEL = {"T2": "完全成功(达目标2)", "T1": "成功(达目标1)", "SL": "失败(先破止损)",
         "SL_AMBIG": "失败(同日双向·保守计)", "NO_ENTRY_NEVER": "未入场(从未回到买点区)",
         "NO_ENTRY_BREAK": "未入场(跳空破位)", "OPEN": "持有中", "NO_DATA": "无数据"}


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 2) if xs else None


def agg(rows):
    n = len(rows)
    c = Counter(r["result"] for r in rows)
    traded = [r for r in rows if r["result"] in WIN + LOSE]
    win_rows = [r for r in traded if r["result"] in WIN and r["ret"] is not None]
    lose_rows = [r for r in traded if r["result"] in LOSE and r["ret"] is not None]
    rets = [r["ret"] for r in traded if r["ret"] is not None]
    have_ret = [r["ret"] for r in rows if r["ret"] is not None]
    holds = [r["hold_days"] for r in traded if r["hold_days"]]
    open_rows = [r for r in rows if r["result"] == "OPEN"]
    aw, al = _avg([r["ret"] for r in win_rows]), _avg([r["ret"] for r in lose_rows])
    srt = sorted(have_ret)
    med = round(srt[len(srt) // 2], 2) if srt else None
    return {
        "n": n,
        "cnt": dict(c),
        "traded": len(traded),
        "win": len(win_rows),
        "lose": len(lose_rows),
        "win_rate": round(100.0 * len(win_rows) / len(traded), 1) if traded else None,
        # 口径B：全部有收益的行（含「持有中」按最新价）以 ret>0 记胜 —— 更保守、不遗漏未了结样本
        "win_rate_all": round(100.0 * sum(1 for x in have_ret if x > 0) / len(have_ret), 1) if have_ret else None,
        "avg_ret": _avg(rets),                    # 已了结平均收益
        "avg_ret_all": _avg(have_ret),            # 全部含浮动
        "median_ret_all": med,
        "avg_win": aw,
        "avg_loss": al,
        "pl_ratio": round(abs(aw / al), 2) if (aw and al and al != 0) else None,  # 盈亏比
        "avg_hold": _avg(holds),
        "no_entry_rate": round(100.0 * (c["NO_ENTRY_NEVER"] + c["NO_ENTRY_BREAK"]) / n, 1) if n else None,
        "open_n": len(open_rows),
        "open_avg_ret": _avg([r["ret"] for r in open_rows]),
        "avg_mfe": _avg([r["mfe"] for r in rows]),
        "avg_mae": _avg([r["mae"] for r in rows]),
    }


def group(rows, key):
    g = defaultdict(list)
    for r in rows:
        g[r[key]].append(r)
    return {k: agg(v) for k, v in sorted(g.items(), key=lambda x: str(x[0]))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true", help="只拉/更新K线缓存")
    ap.add_argument("--refresh", action="store_true", help="强制重拉K线")
    a = ap.parse_args()

    track = load_track()
    cmap = build_code_map()
    codes = sorted({cmap.get(r["code"], guess_prefix(r["code"])) for r in track})
    print(f"跟踪表 {len(track)} 行 / {len(codes)} 只唯一代码")

    store = {}
    if os.path.exists(CACHE) and not a.refresh:
        store = json.load(open(CACHE, encoding="utf-8"))
    store = fetch(store, codes, refresh=a.refresh)
    if a.fetch:
        return 0

    # 校验数据覆盖
    nocov = [c for c in codes if not (store.get(c) or {}).get("bars")]
    if nocov:
        print(f"⚠️ 无K线数据的代码 {len(nocov)} 只：{nocov[:20]}")

    # 逐行模拟
    detail = []
    for r in track:
        full = cmap.get(r["code"], guess_prefix(r["code"]))
        bars = [b for b in (store.get(full) or {}).get("bars", []) if b["date"] <= DATA_END]
        ev = simulate(r, bars)
        detail.append({**r, **ev, "full_code": full})

    meta = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_end": DATA_END,
        "kline_window": f"{START} ~ {END}",
        "signal_dates": sorted({r["date"] for r in detail}),
        "n_rows": len(detail),
        "n_codes": len(codes),
        "n_selftest": len(track),
        "notes": [
            "2026-09-25 为中秋节休市（沪深北交易所公告：9/25–9/27 休市，9/28 起开市），无行情数据属正常。",
            "K线为前复权(qfq)；跟踪表买点/止损/目标位由信号日盘中或收盘价计算，与K线存在 <0.5% 的口径差。",
            "同一只股票可能在不同板块/不同日期多次入选，样本非完全独立（存在伪重复）。",
            "样本期 2026-08-18 ~ 2026-09-28 为连续上涨阶段，缺少震荡/下跌样本，胜率不可外推。",
        ],
    }
    # 稳健性检验：同一只股票只保留首个信号（消除跨板块/跨日伪重复）
    seen, dedup = set(), []
    for r in sorted(detail, key=lambda x: (x["code"], x["date"])):
        if r["code"] in seen:
            continue
        seen.add(r["code"])
        dedup.append(r)

    out = {
        "meta": meta,
        "overall": agg(detail),
        "overall_dedup": agg(dedup),
        "by_sig": group(detail, "sig"),
        "by_sig_dedup": group(dedup, "sig"),
        "by_sector": group(detail, "sector"),
        "by_date": group(detail, "date"),
        "by_shape": group(detail, "shape"),
        "detail": detail,
        "detail_dedup_codes": [r["code"] for r in dedup],
    }
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    o, od = out["overall"], out["overall_dedup"]
    print(f"\n=== 总览（{o['n']} 行 / 已了结 {o['traded']}）===")
    print(f"  胜率(仅已了结) {o['win_rate']}% | 胜率(全部含持有中浮动) {o['win_rate_all']}%")
    print(f"  成功 {o['win']} / 失败 {o['lose']}")
    print(f"  平均收益 已了结 {o['avg_ret']}% | 全部含浮动 {o['avg_ret_all']}% | 中位数 {o['median_ret_all']}%")
    print(f"  平均盈利 {o['avg_win']}% / 平均亏损 {o['avg_loss']}% → 盈亏比 {o['pl_ratio']}")
    print(f"  平均持有 {o['avg_hold']} 交易日 | 未入场率 {o['no_entry_rate']}% | 持有中 {o['open_n']} 行(均浮动 {o['open_avg_ret']}%)")
    print(f"  平均MFE {o['avg_mfe']}% | 平均MAE {o['avg_mae']}%")
    print("  结果分布:", {LABEL.get(k, k): v for k, v in o["cnt"].items()})
    print(f"\n=== 去重口径（每股首个信号，{od['n']} 行）===")
    print(f"  胜率(已了结) {od['win_rate']}% | 胜率(全部) {od['win_rate_all']}% | 盈亏比 {od['pl_ratio']}")
    print(f"  平均收益 已了结 {od['avg_ret']}% | 全部 {od['avg_ret_all']}%")
    print(f"\n按信号类型：")
    for k, v in out["by_sig"].items():
        d = out["by_sig_dedup"].get(k, {})
        print(f"  {k}: n={v['n']} 胜率={v['win_rate']}% 全部口径={v['win_rate_all']}% "
              f"均收益={v['avg_ret']}% 盈亏比={v['pl_ratio']} 未入场={v['no_entry_rate']}%"
              f" ｜去重后 n={d.get('n')} 胜率={d.get('win_rate')}%")
    print(f"\n明细已写：{OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
