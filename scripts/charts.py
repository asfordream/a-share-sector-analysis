#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""板块指数 YTD K线 + 同类子板块对比数据"""
import json, os, subprocess, sys, time

CLI = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sector-webapp/westock_cli.js")
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

PEERS = {
    "A股创新药":  [("创新药", "pt02131362"), ("中药概念", "pt02251325"), ("生物制品", "pt01801152")],
    "算力":       [("算力租赁", "pt02GN2234"), ("数据中心", "pt02041354"), ("服务器", "pt02GN2223"), ("液冷概念", "pt02GN2224")],
    "半导体":     [("半导体产业", "pt02GN2116"), ("半导体设备", "pt02GN2328"), ("半导体材料", "pt02GN2323"), ("先进封装", "pt02GN2166"), ("第四代半导体", "pt02GN2204")],
    "存储":       [("存储器", "pt02GN2124"), ("HBM", "pt02GN2272"), ("SRAM", "pt02GN2291"), ("磁电存储", "pt02GN2295")],
    "人形机器人": [("人形机器人", "pt02GN2238"), ("减速器", "pt02GN2165"), ("机器视觉", "pt02061378")],
    "光通信":     [("光通信", "pt02GN2190"), ("光模块", "pt02GN2211"), ("数据中心", "pt02041354")],
    "CPO":        [("CPO概念", "pt02GN2211"), ("光通信", "pt02GN2190"), ("光芯片", "pt02GN2236"), ("先进封装", "pt02GN2166"), ("光纤概念", "pt02GN2435")],   # 2026-09-23 加入常驻
    "商业航天":   [("商业航天", "pt02GN2306"), ("卫星互联网", "pt02SATNET"), ("军工电子Ⅱ", "pt01801745")],
    "PCB":        [("PCB概念", "pt02101284"), ("消费电子产业", "pt02GN2120"), ("服务器", "pt02GN2223"), ("半导体产业", "pt02GN2116"), ("算力租赁", "pt02GN2234")],
    "电网设备":    [("电网设备", "pt01801738"), ("特高压", "pt02C10006"), ("智能电网", "pt02003581"), ("虚拟电厂", "pt02GN2027")],   # 2026-08-18 加入常驻
    "AI应用":      [("AI应用", "pt02GN2343"), ("人工智能", "pt02003800"), ("人工智能大模型", "pt02GN2228"), ("AIGC", "pt02GN2196"), ("算力租赁", "pt02GN2234")],
}
SELF = {
    "A股创新药": "pt02131362", "算力": "pt02GN2234", "半导体": "pt02GN2116",
    "存储": "pt02GN2124", "人形机器人": "pt02GN2238",
    "光通信": "pt02GN2190", "商业航天": "pt02GN2306",
    "CPO": "pt02GN2211",   # 2026-09-23 加入常驻
    "PCB": "pt02101284",
    "电网设备": "pt01801738",   # 2026-08-18 加入常驻
    "AI应用": "pt02GN2343",
}

# 本次运行的板块清单（11 板块，2026-08-18 移除证券/电力/光模块、新增电网设备；2026-08-31 新增 AI应用；2026-09-04 移除宇树科技概念；2026-09-23 移除元件、新增 CPO）
RUN_NAMES = ["A股创新药", "算力", "半导体", "存储", "人形机器人",
             "光通信", "CPO", "PCB", "商业航天", "电网设备", "AI应用"]


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


# 解析卫星互联网真实代码
sat = parse_table(run(["sector", "search", "卫星互联网", "--limit", "3"]))
satcode = None
for r in sat:
    if r.get("名称") == "卫星互联网":
        satcode = r.get("代码")
if satcode:
    PEERS["商业航天"][1] = ("卫星互联网", satcode)
    sys.stderr.write(f"卫星互联网 -> {satcode}\n")
else:
    PEERS["商业航天"].pop(1)
    sys.stderr.write("卫星互联网 未找到，剔除\n")

TARGETS = [n for n in (sys.argv[1:] or RUN_NAMES) if n in SELF]
for name in TARGETS:
    code = SELF[name]
    sys.stderr.write(f"=== {name} ===\n")
    res = {}
    # YTD 日线（2026-01-01 起，约 150 交易日）
    kl = parse_table(run(["kline", code, "--period", "day", "--limit", "150", "--fq", "qfq"]))
    rows = [(r["date"], num(r["last"])) for r in kl if r.get("date") and num(r.get("last"))]
    rows = [r for r in rows if r[0] >= "2026-01-01"]
    rows.sort()
    res["ytd"] = {"dates": [r[0] for r in rows], "close": [r[1] for r in rows]}

    # 同类板块对比
    peers = PEERS[name]
    q = parse_table(run(["quote", ",".join(c for _, c in peers)]))
    qm = {r["code"]: r for r in q}
    res["peers"] = []
    for label, c in peers:
        r = qm.get(c)
        if not r:
            continue
        res["peers"].append({
            "name": label, "code": c,
            "chg": num(r.get("change_percent")), "chg20d": num(r.get("chg_20d")),
            "chg60d": num(r.get("chg_60d")), "chgYtd": num(r.get("chg_ytd")),
            "pe": num(r.get("pe_ratio")), "pb": num(r.get("pb_ratio")),
        })
    sys.stderr.write(f"  ytd:{len(res['ytd']['dates'])}根 peers:{len(res['peers'])}\n")
    with open(f"{OUT}/{name}_chart.json", "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False)
    time.sleep(0.4)
