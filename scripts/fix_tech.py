#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""补齐 technical 缺口：对指定板块重新拉取 ma/macd/rsi，小批(10)+重试，合并回 data/<板块>.json。

背景：collect.py 用 chunk=25 批量拉 technical，偶发整批返回空（如 28 只只回 3 只）。
本脚本用 chunk=10 重拉并原地修补，避免整轮 collect 重跑。
用法：python3 scripts/fix_tech.py 光通信 A股创新药
"""
import json
import os
import subprocess
import sys
import time

CLI = ("/Applications/WorkBuddy.app/Contents/Resources/app.asar.unpacked/"
       "resources/builtin-skills/westock-data/scripts/index.js")
WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(WS, "data")


def run(args, retries=4):
    for i in range(retries):
        try:
            r = subprocess.run(["node", CLI] + args, capture_output=True,
                               text=True, timeout=180)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout
        except Exception as e:
            sys.stderr.write(f"  ! {e}\n")
        time.sleep(2 + i * 2)
    return ""


def parse_table(text):
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


def fix(name):
    path = os.path.join(OUT, f"{name}.json")
    d = json.load(open(path, encoding="utf-8"))
    U = d["universe"]
    missing = [u for u in U if not u.get("ma20")]
    if not missing:
        print(f"{name}: 无缺口，跳过")
        return 0
    print(f"{name}: 缺口 {len(missing)}/{len(U)} → 重拉")

    tech = {}
    codes = [u["code"] for u in missing]
    for i in range(0, len(codes), 10):
        ch = codes[i:i + 10]
        rows = parse_table(run(["technical", ",".join(ch),
                                "--group", "ma,macd,rsi"]))
        for t in rows:
            tech[t.get("code")] = t
        print(f"  chunk {i // 10 + 1}: +{len(rows)}")
        time.sleep(0.6)

    fixed = 0
    for u in U:
        t = tech.get(u["code"])
        if not t:
            continue
        close = num(t.get("closePrice")) or u.get("price")
        ma20 = num(t.get("ma.MA_20"))
        u["price"] = close or u.get("price")
        u["ma5"] = num(t.get("ma.MA_5"))
        u["ma10"] = num(t.get("ma.MA_10"))
        u["ma20"] = ma20
        u["ma60"] = num(t.get("ma.MA_60"))
        u["ma120"] = num(t.get("ma.MA_120"))
        u["ma250"] = num(t.get("ma.MA_250"))
        u["distMa20"] = (round((close - ma20) / ma20 * 100, 2)
                         if (close and ma20) else None)
        u["distMa60"] = (round((close - u["ma60"]) / u["ma60"] * 100, 2)
                         if (close and u["ma60"]) else None)
        u["distMa120"] = (round((close - u["ma120"]) / u["ma120"] * 100, 2)
                          if (close and u["ma120"]) else None)
        u["distMa250"] = (round((close - u["ma250"]) / u["ma250"] * 100, 2)
                          if (close and u["ma250"]) else None)
        u["qbUptrend"] = bool(ma20 and u["ma60"] and u["ma120"] and ma20 > u["ma60"] > u["ma120"])
        u["rsi6"] = num(t.get("rsi.RSI_6"))
        u["rsi12"] = num(t.get("rsi.RSI_12"))
        u["dif"] = num(t.get("macd.DIF"))
        u["dea"] = num(t.get("macd.DEA"))
        u["macd"] = num(t.get("macd.MACD"))
        u["date"] = t.get("date") or u.get("date")
        fixed += 1

    json.dump(d, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    still = sum(1 for u in U if not u.get("ma20"))
    print(f"  -> 修补 {fixed} 只，剩余缺口 {still}")
    return still


if __name__ == "__main__":
    rc = 0
    for nm in sys.argv[1:]:
        rc += fix(nm)
    sys.exit(1 if rc else 0)
