#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""港股板块数据采集：quote + technical(批量) + kline(并发)，算距MA20%、40日swing low、RSI_6。

要点（已踩坑）：
- CLI 路径 2026-08-10 变更：旧的 WorkBuddy.app builtin-skills/westock-data 已不存在，
  改用工作区内 sector-webapp/westock_cli.js（与 A 股 collect.py 同源）。
- technical 支持批量 codes（chunk=10 + 重试），比逐票快一个数量级；
  但**批量偶发整批空返**，故收尾必须校验 ma20 覆盖率并按缺口重拉。
- kline 只能逐票，用线程池并发（港股 40 只约 20s）。
"""
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(BASE, "sector-webapp", "westock_cli.js")
NODE = os.environ.get("NODE_BIN", "node")
OUTDIR = os.path.join(BASE, "data")
TODAY = os.environ.get("RUNDATE_DASH") or datetime.now().strftime("%Y-%m-%d")
TECH_CHUNK = 10
TECH_RETRY = 4


def run(args, timeout=90):
    try:
        r = subprocess.run([NODE, CLI] + args, capture_output=True, text=True, timeout=timeout)
        return r.stdout
    except Exception:
        return ""


def parse_md_table(text):
    lines = [l for l in text.splitlines() if l.strip().startswith("|")]
    if len(lines) < 2:
        return []
    header = [h.strip() for h in lines[0].strip("|").split("|")]
    rows = []
    for l in lines[2:]:
        cells = [c.strip() for c in l.strip("|").split("|")]
        if len(cells) != len(header):
            continue
        rows.append(dict(zip(header, cells)))
    return rows


def num(v):
    try:
        if v in ("-", "", "N/A", "null", None):
            return None
        return float(v)
    except Exception:
        return None


def fetch_tech(codes):
    """批量技术指标，chunk + 重试；返回 {code: row}"""
    out = {}
    for i in range(0, len(codes), TECH_CHUNK):
        chunk = codes[i:i + TECH_CHUNK]
        for attempt in range(TECH_RETRY):
            txt = run(["technical", ",".join(chunk), "--group", "ma,macd,rsi", "--date", TODAY])
            rows = {r["code"]: r for r in parse_md_table(txt) if r.get("code", "").startswith("hk")}
            if rows:
                out.update(rows)
                break
        missing = [c for c in chunk if c not in out]
        if missing:
            print(f"  [tech retry-single] {missing}", flush=True)
            for c in missing:
                txt = run(["technical", c, "--group", "ma,macd,rsi", "--date", TODAY])
                for r in parse_md_table(txt):
                    if r.get("code", "").startswith("hk"):
                        out[r["code"]] = r
    return out


def fetch_kline(code):
    txt = run(["kline", code, "--period", "day", "--fq", "qfq", "--limit", "40"])
    rows = parse_md_table(txt)
    lows = [num(r.get("low")) for r in rows if num(r.get("low")) not in (None, 0)]
    vols = [num(r.get("volume")) for r in rows if num(r.get("volume")) is not None]
    res = {}
    if lows:
        res["swing_low_40"] = min(lows)
    if rows:
        res["kline_last_date"] = rows[0].get("date")
    # 量能：当日成交量 / 近20日均量
    if len(vols) >= 6:
        base = sum(vols[1:21]) / len(vols[1:21]) if len(vols) > 1 else None
        if base:
            res["vol_ratio_20"] = round(vols[0] / base, 2)
    return code, res


def collect_sector(name, universe):
    codes = [c for c, _ in universe]
    print(f"  [1/3] quote x{len(codes)}", flush=True)
    qrows = {r["code"]: r for r in parse_md_table(run(["quote", ",".join(codes)]))
             if r.get("code", "").startswith("hk")}
    print(f"  [2/3] technical x{len(codes)}", flush=True)
    trows = fetch_tech(codes)
    print(f"  [3/3] kline x{len(codes)} (并发)", flush=True)
    kres = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        for code, res in ex.map(fetch_kline, codes):
            kres[code] = res

    results = []
    for code, disp in universe:
        rec = {"code": code, "name": disp}
        q = qrows.get(code)
        if q:
            for k_src, k_dst in [("price", "price"), ("change_percent", "change_percent"),
                                 ("pe_ratio", "pe_ratio"), ("pb_ratio", "pb_ratio"),
                                 ("dividend_ratio_ttm", "dividend_ratio_ttm"),
                                 ("total_market_cap", "total_market_cap"),
                                 ("chg_5d", "chg_5d"), ("chg_20d", "chg_20d"),
                                 ("chg_60d", "chg_60d"), ("chg_ytd", "chg_ytd"),
                                 ("high_52week", "high_52week"), ("low_52week", "low_52week")]:
                rec[k_dst] = num(q.get(k_src))
            rec["date"] = q.get("time")
        else:
            rec["missing_quote"] = True

        t = trows.get(code)
        if t:
            rec["close"] = num(t.get("closePrice"))
            rec["ma5"] = num(t.get("ma.MA_5"))
            rec["ma10"] = num(t.get("ma.MA_10"))
            rec["ma20"] = num(t.get("ma.MA_20"))
            rec["ma60"] = num(t.get("ma.MA_60"))
            rec["rsi6"] = num(t.get("rsi.RSI_6"))
            rec["rsi12"] = num(t.get("rsi.RSI_12"))
            rec["dif"] = num(t.get("macd.DIF"))
            rec["dea"] = num(t.get("macd.DEA"))
            rec["macd"] = num(t.get("macd.MACD"))
            rec["tech_date"] = t.get("date")
        else:
            rec["missing_tech"] = True

        rec.update(kres.get(code, {}))

        c = rec.get("close") or rec.get("price")
        if c and rec.get("ma20"):
            rec["dist_ma20_pct"] = round((c - rec["ma20"]) / rec["ma20"] * 100, 2)
        if rec.get("ma5") is not None and rec.get("ma10") is not None:
            rec["ma5_gt_ma10"] = rec["ma5"] > rec["ma10"]
        results.append(rec)

    os.makedirs(OUTDIR, exist_ok=True)
    outpath = os.path.join(OUTDIR, f"港股{name}.json")
    with open(outpath, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    n_q = sum(1 for r in results if r.get("price") is not None)
    n_ma = sum(1 for r in results if r.get("ma20") is not None)
    n_sl = sum(1 for r in results if r.get("swing_low_40") is not None)
    print(f"[OK] 港股{name}: {len(results)} 只 | quote {n_q} | ma20 {n_ma} | swingLow {n_sl} -> {outpath}", flush=True)
    if n_ma < len(results):
        miss = [r["name"] for r in results if r.get("ma20") is None]
        print(f"  [WARN] ma20 缺口: {miss}", flush=True)
    return results


SECTORS = {
    "半导体": [
        ("hk00981", "中芯国际"), ("hk01347", "华虹宏力"), ("hk00522", "ASMPT"),
        ("hk01385", "上海复旦"), ("hk00085", "中电华大"), ("hk03986", "兆易创新"),
        ("hk06809", "澜起科技"), ("hk02676", "纳芯微"), ("hk02631", "天岳先进"),
        ("hk00501", "豪威集团"), ("hk02701", "国民技术"), ("hk06082", "壁仞科技"),
        ("hk09903", "天数智芯"), ("hk02577", "英诺赛科"), ("hk02878", "晶门半导体"),
        ("hk01912", "康特隆"), ("hk02203", "脑洞科技"), ("hk02166", "芯智控股"),
        ("hk00243", "品质国际"), ("hk06908", "宏光半导体"),
    ],
    "互联网": [
        ("hk00700", "腾讯控股"), ("hk09988", "阿里巴巴"), ("hk03690", "美团"),
        ("hk09618", "京东集团"), ("hk01024", "快手"), ("hk09999", "网易"),
        ("hk09888", "百度集团"), ("hk09626", "哔哩哔哩"), ("hk09961", "携程集团"),
        ("hk01810", "小米集团"), ("hk01698", "腾讯音乐"), ("hk02423", "贝壳"),
        ("hk00780", "同程旅行"), ("hk09898", "微博"), ("hk00772", "阅文集团"),
        ("hk03888", "金山软件"), ("hk00020", "商汤"), ("hk02390", "知乎"),
        ("hk01797", "东方甄选"), ("hk09896", "名创优品"), ("hk09899", "网易云音乐"),
        ("hk02400", "心动公司"),
    ],
}

if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    for sname, uni in SECTORS.items():
        if which not in ("all", sname):
            continue
        print(f"=== 采集 港股{sname} ({len(uni)}只) date={TODAY} ===", flush=True)
        collect_sector(sname, uni)
