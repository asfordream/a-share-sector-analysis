#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Feishu push for sector deep-analysis reports (研股股).

统一推送模型：分析报告(文本) + 深度分析 HTML 文件 成对发送。

用法：
  python3 push.py            # 批量 all：日报卡片 + 11 HTML 附件，推 私信 + 固定群(小韭菜)
  python3 push.py --group-only  # 批量仅群（补推用，避免重复私信）
  python3 push.py 板块名     # 单板块：该板块 markdown + HTML 文件（私信 + 群）

lark-cli --file 只接受 CWD 相对路径，故 cwd 固定为工作区根目录。

注：小韭菜群仅由 A 股自动化推送；港股自动化不推群（用户 2026-08-07 指定）。
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UID = os.environ.get("FEISHU_USER_OPEN_ID", "")
LARK = os.environ.get("LARK_CLI", "lark-cli")
ENV = dict(os.environ,
           LARKSUITE_CLI_NO_UPDATE_NOTIFIER="1",
           LARKSUITE_CLI_NO_SKILLS_NOTIFIER="1")

# 固定额外推送的群：群名 -> chat_id（硬编码优先，不依赖 bot 能否被 chat-list 列出）
# 仅 A 股自动化推此群，港股自动化不推群（用户 2026-08-07 指定）。
GROUPS = {
    "小韭菜": os.environ.get("FEISHU_GROUP_CHAT_ID", ""),
}

# 推送模式：all=私信+群（日常调度），group-only=仅群（补推用，避免重复私信）
CURRENT_MODE = "all"

# 批量模式下 HTML 文件的发送顺序（稳定）
BATCH_ORDER = ["A股创新药", "算力", "半导体", "存储", "证券", "人形机器人",
               "光通信", "光模块", "PCB", "商业航天", "电力", "银行"]


def run(args):
    r = subprocess.run(args, cwd=WS, env=ENV, capture_output=True, text=True)
    out = (r.stdout + r.stderr).strip()
    return r.returncode, out


def _chat_args(target):
    if "user_id" in target:
        return ["--user-id", target["user_id"]]
    return ["--chat-id", target["chat_id"]]


def _targets():
    ts = []
    if CURRENT_MODE == "all":
        ts.append({"user_id": UID})
    for _name, cid in GROUPS.items():
        ts.append({"chat_id": cid})
    return ts


def _send_multi(base_args):
    """对当前模式下的所有目标（私信 + 群）逐一发送，汇总结果。"""
    rc_all = 0
    outs = []
    for t in _targets():
        args = base_args + _chat_args(t)
        r = subprocess.run(args, cwd=WS, env=ENV, capture_output=True, text=True)
        outs.append(r.stdout + r.stderr)
        if r.returncode != 0:
            rc_all = 1
    return rc_all, "\n".join(outs)


def send_md(text):
    return _send_multi([LARK, "im", "+messages-send", "--as", "bot", "--markdown", text])


def send_file(rel):
    return _send_multi([LARK, "im", "+messages-send", "--as", "bot", "--file", rel])


def send_card(card):
    # interactive 卡片：卡片 lark_md 才渲染 <font color>，post markdown 不渲染
    return _send_multi([LARK, "im", "+messages-send", "--as", "bot",
                        "--content", json.dumps(card, ensure_ascii=False),
                        "--msg-type", "interactive"])


# 评级→emoji 圆点（颜色强化只用 emoji，严禁 <font>/<color>，飞书 markdown 会原样显示）
EMOJI = {"加码": "🔴", "加仓": "🔴", "持有": "🟡", "观察": "🟢", "减仓": "🟢",
         "清仓": "🟢", "等待证据": "🟢", "对冲": "🟢", "放弃": "🟢",
         "重新评估": "🟢", "观察名单": "🟢"}


def emoji_of(rating):
    return EMOJI.get(rating, "🟢")


def color_of(rating):
    # 加码/持有=红（积极），观察=绿（观望）——仅用于兼容旧引用
    return "red" if rating in ("加码", "持有") else "green"


def color_lag(lag_txt):
    """落后补涨文本逐段着色：正% 🔴 / 负% 🟢。"""
    if not lag_txt or "无" in lag_txt:
        return lag_txt
    parts = [p.strip() for p in lag_txt.split("/")]
    out = []
    for p in parts:
        m = re.search(r"([+-]?\d+(?:\.\d+)?%)", p)
        neg = m and m.group(1).startswith("-")
        out.append(f"{'🟢' if neg else '🔴'} {p}")
    return " / ".join(out)


def cand_text(cands):
    """回抽确认候选 → 名称(距MA20%)。空则提示已站上MA20。"""
    if not cands:
        return "无（板块个股普遍已站上MA20）"
    return " / ".join(f"{c['name']}({c['distMa20']:+.2f}%)" for c in cands)


def short(s, n=46):
    s = s.replace("\n", " ").strip()
    return s if len(s) <= n else s[:n] + "…"


def load_sectors():
    with open(os.path.join(WS, "data", "_summary.json"), encoding="utf-8") as f:
        return json.load(f)


def by_name(sectors):
    return {s["name"]: s for s in sectors}


def daily_report_card(sectors, rundate):
    """板块深度分析日报卡片：每板块 一句话定位 + 评级(emoji) + 落后补涨 + 回抽确认。"""
    elements = []
    for i, s in enumerate(sectors, 1):
        e = emoji_of(s["rating"])
        # 主行
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md",
                     "content": f"{i}. {e} 【{s['rating']}】{s['name']}｜{s['position']}"}
        })
        # 子行1：落后补涨（带涨跌色）
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md",
                     "content": f"　　落后补涨：{color_lag(s.get('lag', ''))}"}
        })
        # 子行2：回抽确认（名称+距MA20%）
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md",
                     "content": f"　　回抽确认：{cand_text(s.get('cands', []))}"}
        })
    elements.append({"tag": "hr"})
    jia = [s["name"] for s in sectors if s["rating"] in ("加码", "持有")]
    guan = [s["name"] for s in sectors if s["rating"] == "观察"]
    elements.append({
        "tag": "div",
        "text": {
            "tag": "lark_md",
            "content": (f"🔴 加码/持有：{', '.join(jia)}　🟢 观察：{', '.join(guan)}")
        }
    })
    elements.append({
        "tag": "note",
        "elements": [{"tag": "plain_text",
                      "content": "本报告仅供研究参考，不构成个人投资建议"}]
    })
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text",
                      "content": f"📊 研股股·A股板块深度分析日报（{rundate}）"}
        },
        "elements": elements
    }


def batch_mode(sectors, rundate):
    bmap = by_name(sectors)
    ordered = [bmap[n] for n in BATCH_ORDER if n in bmap]

    # 1) 板块深度分析日报（卡片）
    rc, out = send_card(daily_report_card(ordered, rundate))
    if '"ok": true' in out:
        print("OK  daily report card")
    else:
        print(f"FAIL daily report: {out[:160]}")

    # 2) 逐板块发送深度分析 HTML 文件
    ok_file = 0
    for s in ordered:
        rel = os.path.basename(s["path"])
        rc, out = send_file(rel)
        if '"ok": true' in out:
            ok_file += 1
            print(f"OK  file {s['name']}")
        else:
            print(f"FAIL file {s['name']}: {out[:160]}")
    print(f"\nDONE daily_report=1 file={ok_file}/{len(ordered)}")
    return 0 if ok_file == len(ordered) else 1


def single_mode(sectors, name, rundate):
    bmap = by_name(sectors)
    if name not in bmap:
        print(f"ERROR: 板块 '{name}' 不在 _summary.json 中")
        return 2
    s = bmap[name]
    md = (f"{name}｜{s['position']}｜评级：{s['rating']}"
          f"｜落后补涨：{s['lag']}｜多空：{short(s['bull'])}（多）/ {short(s['bear'])}（空）")
    rc, out = send_md(md)
    if '"ok": true' in out:
        print(f"OK  md   {name}")
    else:
        print(f"FAIL md   {name}: {out[:160]}")
    rel = os.path.basename(s["path"])
    rc, out = send_file(rel)
    if rc == 0 and '"ok": true' in out:
        print(f"OK  file {name}")
    else:
        print(f"FAIL file {name}: {out[:160]}")
    return 0


def main():
    sectors = load_sectors()
    rundate = datetime.now().strftime("%Y%m%d")
    args = sys.argv[1:]
    global CURRENT_MODE
    if args and args[0] in ("--all", "--group-only"):
        CURRENT_MODE = args[0].lstrip("-")  # "all" / "group-only"
        rest = args[1:]
    else:
        CURRENT_MODE = "all"
        rest = args
    if rest:
        return single_mode(sectors, rest[0], rundate)
    return batch_mode(sectors, rundate)


if __name__ == "__main__":
    sys.exit(main())
