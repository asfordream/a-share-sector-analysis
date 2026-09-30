#!/usr/bin/env python3
"""按 Step G 规则从 data/_summary.json 生成当日自选股候选清单。

规则（2026-08-18 用户拍板，取代原「仅取 rating∈{加码,持有}」）：
- 仅取「评级 × 技术面 裁决逻辑总表」中 **裁决 emoji == 🔴 的板块**（技术面确认偏强，
  如 加码/持有・双强共振、加码/持有・健康回踩、观察・可上调 等；裁决 emoji 由
  tech4.compute 实时算出，不按评级粗筛）
- cands ：回抽确认候选（距MA20 0%~-10%、RSI_6 32~64、量能强/中）—— 直接取 _summary.cands
- mups ：主升浪买点区（中期多头 MA20>MA60 且近20日≥10%、距MA20 -15%~+20%、
         量能强/中、(阳线 或 RSI_6 35~60)）—— 直接取 _summary.mups
         （_summary.mups 由 render.py 的 _mup 标记产出，口径与报告表4 同源）
- 按 code 去重合并得当日清单 N（cands 与 mups 可能重叠，只写一次）
- ⚠️ 2026-08-27 用户拍板：仅「确认态==已确认」的候选进入 N（回抽确认 + 主升浪买点区均须已确认）

输出 data/_g_final.json（codes + detail）。打印按 ≤20 分批，供 portfolio_watchlist_batch_add 使用。
"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tech4  # noqa: E402  四层技术面体检 + 评级×技术面裁决

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")


def main():
    S = json.load(open(os.path.join(DATA, "_summary.json"), encoding="utf-8"))
    seen = {}
    n_c_confirm = n_c_wait = 0  # 回抽确认候选 确认态拆分（仅 🔴 板块）
    n_m_confirm = n_m_wait = 0  # 主升浪买点区 确认态拆分（仅 🔴 板块）
    for s in S:
        U, sq = tech4.load_universe(DATA, s["name"])
        t4 = tech4.compute(U, sq, s.get("rating"))
        emo = t4["conclusion_emo"] if t4 else "-"
        vt = t4["verdict_type"] if t4 else "MISSING"
        red = emo == "🔴"
        print(f"  {'🔴 入选' if red else '   跳过'} {s['name']:<8} {s.get('rating','?'):<4} 【{vt}】{emo}")
        if not red:
            continue
        for src, lst in (("cand", s["cands"]), ("mup", s["mups"])):
            for c in lst:
                code = (c.get("code") or "").strip()
                if not code:
                    print("  !! 缺 code:", s["name"], c.get("name"))
                    continue
                cf = c.get("confirm")
                if src == "cand":
                    n_c_confirm += (cf == "已确认")
                    n_c_wait += (cf != "已确认")
                else:
                    n_m_confirm += (cf == "已确认")
                    n_m_wait += (cf != "已确认")
                # 仅「已确认」候选进入写股清单（2026-08-27 用户拍板：确认态作为写入门槛）
                if cf != "已确认":
                    continue
                if code not in seen:
                    seen[code] = {"name": c.get("name"), "sector": s["name"],
                                  "src": [src], "volGrade": c.get("volGrade"),
                                  "volScore": c.get("volScore"), "distMa20": c.get("distMa20"),
                                  "confirm": c.get("confirm")}
                elif src not in seen[code]["src"]:
                    seen[code]["src"].append(src)
    codes = list(seen.keys())
    json.dump({"codes": codes, "detail": seen},
              open(os.path.join(DATA, "_g_final.json"), "w"), ensure_ascii=False, indent=2)
    print(f"候选 N={len(codes)}")
    print(f"  回抽确认确认态(仅 🔴 板块 cands)：已确认 {n_c_confirm} / 待确认 {n_c_wait}")
    print(f"  主升浪确认态(仅 🔴 板块 mups)：已确认 {n_m_confirm} / 待确认 {n_m_wait}")
    for i in range(0, len(codes), 20):
        print(f"BATCH{i//20+1}: " + ",".join(codes[i:i+20]))
    return codes


if __name__ == "__main__":
    main()
