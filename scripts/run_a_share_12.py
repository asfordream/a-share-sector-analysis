#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重跑 A股 12 板块：顺序生成（gen_sector_report.py）→ 重命名到工作区根目录（<板块>板块深度分析_<ts>.html，与自动化一致）
→ 解析每板块 per-board JSON（rating/oneLiner/cands+volGrade/stocks）→ 过滤量能 强/中 → 汇总 data/_summary.json。

量能硬门槛（固定格式）：cands 仅保留 volGrade ∈ {强,中}（volScore≥40）；弱(<40) 一律剔除。
"""
import subprocess, json, os, re

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORTS = os.path.join(WS, "reports", "A股")
GEN = os.path.join(WS, "sector-webapp", "gen_sector_report.py")
PY = os.environ.get("PYTHON_BIN", "python3")

# (展示名, universe key)
BOARDS = [
    ("A股创新药", "创新药"),
    ("算力", "AI算力(算力租赁)"),
    ("半导体", "半导体"),
    ("存储", "存储芯片"),
    ("证券", "证券"),
    ("人形机器人", "人形机器人"),
    ("光通信", "光通信"),
    ("光模块", "CPO概念"),
    ("PCB", "PCB"),
    ("商业航天", "商业航天"),
    ("电力", "电力"),
]
PASS = ("强", "中")


def gen(key):
    r = subprocess.run([PY, GEN, "--market", "A股", "--sector", key],
                       capture_output=True, text=True)
    m = re.search(r"报告:\s*(\S+)", r.stdout)
    if not m:
        sys.stderr.write(f"[ERR] {key}: 未找到报告行\nSTDOUT:{r.stdout[-300:]}\nSTDERR:{r.stderr[-400:]}\n")
        return None
    return m.group(1)


def parse_and_move(key, display, html_path):
    m = re.search(r"_(\d{8}_\d{6})\.html$", html_path)
    ts = m.group(1) if m else datetime_now()
    json_path = html_path[:-5] + ".json"
    base = f"{display}板块深度分析_{ts}"
    new_html = os.path.join(WS, base + ".html")
    new_json = os.path.join(WS, base + ".json")
    d = json.load(open(json_path, encoding="utf-8"))
    os.replace(html_path, new_html)
    if os.path.exists(json_path):
        os.replace(json_path, new_json)
    stocks = {s["name"]: s for s in d.get("stocks", [])}
    cands = []
    for c in d.get("cands", []):
        if c.get("volGrade") not in PASS:
            continue
        st = stocks.get(c["name"])
        cands.append({
            "name": c["name"],
            "code": st.get("code") if st else None,
            "distMa20": c.get("distMA20"),
            "volScore": c.get("volScore"),
            "volGrade": c.get("volGrade"),
            "volDetail": c.get("volDetail"),
        })
    valid = [s for s in d.get("stocks", []) if isinstance(s.get("distMA20"), (int, float))]
    sw = sorted(valid, key=lambda x: x["distMA20"])[:3]
    lag = " / ".join(f"{s['name']}{s['distMA20']:+.2f}%" for s in sw)
    return {
        "name": display,
        "path": new_html,
        "rating": d.get("rating"),
        "position": d.get("oneLiner"),
        "lag": lag,
        "cands": cands,
    }


def datetime_now():
    import datetime
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def main():
    acc = []
    for display, key in BOARDS:
        print(f"=== {display} ({key}) ===", flush=True)
        html = gen(key)
        if not html:
            continue
        try:
            entry = parse_and_move(key, display, html)
        except Exception as e:
            sys.stderr.write(f"[ERR] {display}: {e}\n")
            continue
        acc.append(entry)
        print(f"  rating={entry['rating']} 强/中候选={len(entry['cands'])}", flush=True)
        import time as _t
        _t.sleep(3)
    out = os.path.join(WS, "data", "_summary.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(acc, f, ensure_ascii=False, indent=1)
    print(f"\n_summary.json 写入: {len(acc)} 板块 -> {out}", flush=True)
    tot = sum(len(e["cands"]) for e in acc)
    print(f"强/中回抽候选合计: {tot} 只", flush=True)


if __name__ == "__main__":
    main()
