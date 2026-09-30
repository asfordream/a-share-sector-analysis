#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
采集 A股 自动化覆盖的 12 个板块成分股，按流通市值取每个板块 top 28，
全局去重，输出 JSON 供写入腾讯自选股「板块选股」分组。
"""
import subprocess, re, json, sys

NODE = os.environ.get("NODE_BIN", "node")
CLI  = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sector-webapp/westock_cli.js")

# (展示名, 搜索词, 偏好名称关键字, 已知pt码)
SECTORS = [
    ("创新药",       "创新药",     "创新药",     None),
    ("算力",         "算力租赁",   "算力租赁",   None),
    ("半导体",       "半导体",     "半导体产业", None),
    ("存储",         "存储",       "存储器",     "pt02GN2124"),
    ("证券",         "证券",       "证券",       None),
    ("人形机器人",   "人形机器人", "人形机器人", None),
    ("光通信",       "光通信",     "光通信",     None),
    ("光模块",       "光模块",     "光模块",     None),
    ("PCB",          "PCB概念",    "PCB概念",    "pt02101284"),
    ("商业航天",     "商业航天",   "商业航天",   None),
    ("电力",         "电力",       "电力",       None),
]

TOPN = 40

def run(args):
    p = subprocess.run([NODE, CLI] + args, capture_output=True, text=True, timeout=120)
    return p.stdout

def parse_md_table(text):
    """返回 (headers, rows)。"""
    lines = [l for l in text.splitlines() if l.strip().startswith("|")]
    if not lines:
        return [], []
    def split_row(l):
        parts = [c.strip() for c in l.strip().strip("|").split("|")]
        return parts
    headers = split_row(lines[0])
    rows = []
    for l in lines[1:]:
        cells = split_row(l)
        if set(cells) <= {"", "---", ":", "-"}:
            continue  # 分隔行
        if len(cells) != len(headers):
            continue
        rows.append(dict(zip(headers, cells)))
    return headers, rows

def search_code(term, prefer):
    out = run(["sector", "search", term])
    headers, rows = parse_md_table(out)
    if "代码" not in headers or "名称" not in headers:
        return None
    ci, ni = headers.index("代码"), headers.index("名称")
    # 优先：名称==prefer 或 包含 prefer
    for r in rows:
        if r["名称"] == prefer:
            return r["代码"]
    for r in rows:
        if prefer in r["名称"]:
            return r["代码"]
    return rows[0]["代码"] if rows else None

def get_constituents(pt):
    out = run(["sector", "constituent", pt, "--limit", "260"])
    headers, rows = parse_md_table(out)
    if "StockCode" not in headers or "StockName" not in headers:
        return []
    ci, ni = headers.index("StockCode"), headers.index("StockName")
    res = []
    for r in rows:
        code = r["StockCode"].strip()
        name = r["StockName"].strip()
        if not re.match(r"^(sh|sz|bj)\d+$", code):
            continue
        if "ST" in name.upper() or name.startswith("*"):
            continue
        if code.startswith("bj"):
            continue
        res.append((code, name))
    return res

def quote_mcap(codes):
    """返回 {code: circulating_market_cap(float)}。分批避免大板块截断/限流。"""
    m = {}
    for i in range(0, len(codes), 50):
        chunk = codes[i:i+50]
        out = run(["quote", ",".join(chunk)])
        headers, rows = parse_md_table(out)
        if "code" not in headers or "circulating_market_cap" not in headers:
            continue
        ci, mi = headers.index("code"), headers.index("circulating_market_cap")
        for r in rows:
            try:
                m[r["code"].strip()] = float(r["circulating_market_cap"])
            except (ValueError, KeyError):
                pass
    return m

def main():
    universe = {}
    all_codes = []
    seen = set()
    log = []
    for label, term, prefer, known in SECTORS:
        pt = known or search_code(term, prefer)
        if not pt:
            log.append(f"[跳过] {label}: 未找到板块代码")
            continue
        cons = get_constituents(pt)
        if not cons:
            log.append(f"[跳过] {label}: 成分股为空 ({pt})")
            continue
        codes = [c for c, _ in cons]
        # 按流通市值取 top N
        if len(codes) > TOPN:
            mcap = quote_mcap(codes)
            codes_sorted = sorted(codes, key=lambda c: mcap.get(c, 0), reverse=True)
            top = codes_sorted[:TOPN]
        else:
            top = codes
        # 去重
        new = [c for c in top if c not in seen]
        seen.update(new)
        all_codes.extend(new)
        universe[label] = new
        log.append(f"[OK] {label}: 板块码={pt} 成分={len(cons)} 取top={len(new)}")

    out = {
        "market": "A股",
        "group_target": "板块选股(id=11)",
        "sectors": universe,
        "all_codes": all_codes,
        "total": len(all_codes),
    }
    with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sector-webapp/data/auto_sectors_universe.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\n".join(log))
    print(f"\n汇总：{len(SECTORS)} 板块，去重后共 {len(all_codes)} 只唯一成分股")
    print("已写入 data/auto_sectors_universe.json")

if __name__ == "__main__":
    main()
