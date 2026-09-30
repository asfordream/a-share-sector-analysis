#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""板块数据采集：constituent -> quote -> technical -> JSON"""
import json, os, subprocess, sys, time

CLI = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sector-webapp/westock_cli.js")
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
os.makedirs(OUT, exist_ok=True)

SECTORS = {
    "A股创新药":   ("pt02131362", "创新药"),
    "算力":        ("pt02GN2234", "算力租赁"),
    "半导体":      ("pt02GN2116", "半导体产业"),
    "存储":        ("pt02GN2124", "存储器"),
    "人形机器人":  ("pt02GN2238", "人形机器人"),
    "光通信":      ("pt02GN2190", "光通信"),
    "CPO":         ("pt02GN2211", "共封装光模块(CPO)"),   # 2026-09-23 加入常驻（第11板块）
    "商业航天":    ("pt02GN2306", "商业航天"),
    "PCB":         ("pt01850822", "印制电路板(申万三级)"),
    "电网设备":    ("pt01801738", "电网设备(申万二级)"),   # 2026-08-18 加入常驻（移除证券/电力/光模块）
    "AI应用":      ("pt02GN2343", "AI应用"),               # 2026-08-31 加入常驻（第12板块）
}

# 部分板块成分口径与指数行情口径不同：成分用申万纯业务清单，
# 指数行情(当日涨跌/YTD)用概念指数（盘中实时跳动）。
INDEX_OVERRIDE = {
    "PCB": "pt02101284",   # 申万三级指数盘中不跳动 → 用 PCB概念指数取当日/YTD
}


def run(args, retries=3):
    for i in range(retries):
        try:
            r = subprocess.run(["node", CLI] + args, capture_output=True, text=True, timeout=180)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout
        except Exception as e:
            sys.stderr.write(f"  ! {e}\n")
        time.sleep(2 + i * 2)
    return ""


def parse_table(text):
    """解析 markdown 表格 -> list[dict]"""
    lines = [l.strip() for l in text.splitlines() if l.strip().startswith("|")]
    if len(lines) < 3:
        return []
    hdr = [c.strip() for c in lines[0].strip("|").split("|")]
    rows = []
    for l in lines[2:]:
        cells = [c.strip() for c in l.strip("|").split("|")]
        if len(cells) != len(hdr):
            continue
        rows.append(dict(zip(hdr, cells)))
    return rows


def num(v, d=None):
    try:
        if v in ("", "-", "None", "null", "N/A"):
            return d
        return float(v)
    except Exception:
        return d


def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def collect(name, code):
    sys.stderr.write(f"\n=== {name} ({code}) ===\n")
    res = {"sector": name, "code": code, "universe": [], "sector_quote": None}

    # 板块自身行情（指数口径可被 INDEX_OVERRIDE 覆盖）
    idx_code = INDEX_OVERRIDE.get(name, code)
    sq = parse_table(run(["quote", idx_code]))
    if sq:
        res["sector_quote"] = sq[0]

    # 成分股
    ct = parse_table(run(["sector", "constituent", code, "--limit", "220"]))
    codes = []
    for r in ct:
        c = r.get("StockCode", "")
        n = r.get("StockName", "")
        if not c or "ST" in n.upper():
            continue
        if c.startswith("bj"):          # 剔除北交所（流动性差）
            continue
        codes.append(c)
    sys.stderr.write(f"  成分股(过滤后): {len(codes)}\n")
    if not codes:
        return res

    # 批量行情
    quotes = []
    for ch in chunks(codes, 40):
        quotes += parse_table(run(["quote", ",".join(ch)]))
        time.sleep(0.4)
    sys.stderr.write(f"  行情: {len(quotes)}\n")

    # 按流通市值排序取前 40
    for q in quotes:
        q["_mc"] = num(q.get("circulating_market_cap"), 0) or 0
    quotes = [q for q in quotes if q.get("name") and num(q.get("price"), 0)]
    quotes.sort(key=lambda x: -x["_mc"])
    top = quotes[:40]
    tcodes = [q["code"] for q in top]

    # 技术指标
    tech = {}
    for ch in chunks(tcodes, 25):
        for t in parse_table(run(["technical", ",".join(ch), "--group", "ma,macd,rsi"])):
            tech[t.get("code")] = t
        time.sleep(0.4)
    sys.stderr.write(f"  技术: {len(tech)}\n")

    # 40日K线最低(失效价/破底位)；westock 个股 kline 需 sh/sz 前缀
    def _kcode(c):
        if c.startswith(("sh", "sz", "bj")):
            return c
        return ("sh" if c[:1] == "6" else "sz") + c
    # 失效价(近40日最低)统一由 swing.py 批量 K 线计算（更快），此处占位
    for q in top:
        q["_swingLow"], q["_swingLowDate"] = None, None

    for q in top:
        c = q["code"]
        t = tech.get(c, {})
        close = num(t.get("closePrice")) or num(q.get("price"))
        ma20 = num(t.get("ma.MA_20"))
        ma5, ma10 = num(t.get("ma.MA_5")), num(t.get("ma.MA_10"))
        ma60 = num(t.get("ma.MA_60"))
        ma120 = num(t.get("ma.MA_120"))
        ma250 = num(t.get("ma.MA_250"))
        distMa60 = round((close - ma60) / ma60 * 100, 2) if (close and ma60) else None
        distMa120 = round((close - ma120) / ma120 * 100, 2) if (close and ma120) else None
        distMa250 = round((close - ma250) / ma250 * 100, 2) if (close and ma250) else None
        qbUptrend = bool(ma20 and ma60 and ma120 and ma20 > ma60 > ma120)
        res["universe"].append({
            "code": c,
            "name": q.get("name"),
            "price": close,
            "chg": num(q.get("change_percent")),
            "chg5d": num(q.get("chg_5d")),
            "chg20d": num(q.get("chg_20d")),
            "chg60d": num(q.get("chg_60d")),
            "chgYtd": num(q.get("chg_ytd")),
            "pe": num(q.get("pe_ratio")),
            "peFwd": num(q.get("pe_fwd")),
            "pb": num(q.get("pb_ratio")),
            "mcap": num(q.get("total_market_cap")),
            "fcap": num(q.get("circulating_market_cap")),
            "hi52": num(q.get("high_52week")),
            "lo52": num(q.get("low_52week")),
            "turnover": num(q.get("turnover_rate")),
            "amount": num(q.get("amount")),
            "volRatio": num(q.get("volume_ratio")),   # 量比(时间归一化)：盘中放量比口径
            "ma5": ma5, "ma10": ma10, "ma20": ma20, "ma60": ma60,
            "ma120": ma120, "ma250": ma250,
            "distMa20": round((close - ma20) / ma20 * 100, 2) if (close and ma20) else None,
            "distMa60": distMa60, "distMa120": distMa120, "distMa250": distMa250,
            "qbUptrend": qbUptrend,
            "reboundPct": round((close - q.get("_swingLow")) / q.get("_swingLow") * 100, 2)
                            if (close and q.get("_swingLow")) else None,
            "rsi6": num(t.get("rsi.RSI_6")),
            "rsi12": num(t.get("rsi.RSI_12")),
            "dif": num(t.get("macd.DIF")),
            "dea": num(t.get("macd.DEA")),
            "macd": num(t.get("macd.MACD")),
            "swingLow": q.get("_swingLow"),
            "swingLowDate": q.get("_swingLowDate"),
            "date": t.get("date") or q.get("time"),
        })
    return res


if __name__ == "__main__":
    targets = sys.argv[1:] or list(SECTORS.keys())
    for nm in targets:
        cd, label = SECTORS[nm]
        d = collect(nm, cd)
        d["label"] = label
        with open(f"{OUT}/{nm}.json", "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        sys.stderr.write(f"  -> saved {nm}.json ({len(d['universe'])} 只)\n")
