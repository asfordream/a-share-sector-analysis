#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reconcile today's run after swapping CPO -> 光模块:
- recall 2 CPO messages (file + post) and the old aggregate card
- send 光模块's 2 messages (markdown + file)
- re-send the aggregate CARD (now lists 光模块, no CPO), with font-color ratings
"""
import json
import os
import subprocess
import sys

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UID = os.environ.get("FEISHU_USER_OPEN_ID", "")
LARK = os.environ.get("LARK_CLI", "lark-cli")
ENV = dict(os.environ,
           LARKSUITE_CLI_NO_UPDATE_NOTIFIER="1",
           LARKSUITE_CLI_NO_SKILLS_NOTIFIER="1")

CPO_FILE = os.environ.get("FEISHU_MSG_CPO_FILE", "")
CPO_POST = os.environ.get("FEISHU_MSG_CPO_POST", "")
AGG_CARD = os.environ.get("FEISHU_MSG_AGG_CARD", "")


def run(args):
    r = subprocess.run(args, cwd=WS, env=ENV, capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()


def send_md(text):
    return run([LARK, "im", "+messages-send", "--as", "bot", "--user-id", UID, "--markdown", text])


def send_file(rel):
    return run([LARK, "im", "+messages-send", "--as", "bot", "--user-id", UID, "--file", rel])


def send_card(card):
    return run([LARK, "im", "+messages-send", "--as", "bot", "--user-id", UID,
                "--content", json.dumps(card, ensure_ascii=False), "--msg-type", "interactive"])


def color_of(rating):
    return "red" if rating in ("加码", "持有") else "green"


def main():
    sectors = json.load(open(f"{WS}/data/_summary.json", encoding="utf-8"))

    # 1) recall stale messages
    for mid, tag in ((CPO_FILE, "CPO file"), (CPO_POST, "CPO post"), (AGG_CARD, "agg card")):
        rc, out = run([LARK, "im", "messages", "delete", "--as", "bot", "--message-id", mid, "--yes"])
        print(f"recall {tag}: rc={rc} {'OK' if 'ok' in out and 'true' in out else 'CHECK'}")

    # 2) send 光模块 messages
    gm = next(s for s in sectors if s["name"] == "光模块")
    md = (f"【9/10 光模块】{gm['position']}｜评级：{gm['rating']}"
          f"｜落后补涨：{gm['lag']}｜多空：{gm['bull'][:44]}（多）/ {gm['bear'][:44]}（空）")
    rc, out = send_md(md)
    print(f"send 光模块 md: rc={rc} {'OK' if 'ok' in out and 'true' in out else 'FAIL'}")
    rc, out = send_file("光模块板块深度分析_20260806.html")
    print(f"send 光模块 file: rc={rc} {'OK' if 'ok' in out and 'true' in out else 'FAIL'}")

    # 3) re-send aggregate CARD
    elements = []
    for i, s in enumerate(sectors, 1):
        c = color_of(s["rating"])
        line = (f"{i}. <font color=\"{c}\">【{s['rating']}】</font> "
                f"{s['name']}｜{s['position']}｜落后补涨：{s['lag']}")
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": line}})
    elements.append({"tag": "hr"})
    elements.append({
        "tag": "div",
        "text": {
            "tag": "lark_md",
            "content": ("<font color=\"red\">加码</font>/<font color=\"red\">持有</font> = 红（积极）　"
                        "<font color=\"green\">观察</font> = 绿（观望）")
        }
    })
    elements.append({
        "tag": "note",
        "elements": [{"tag": "plain_text",
                      "content": "本报告仅供研究参考，不构成个人投资建议"}]
    })
    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text",
                      "content": "📊 研股股·10板块深度分析日报（20260806）"}
        },
        "elements": elements
    }
    rc, out = send_card(card)
    print(f"send agg card: rc={rc} {'OK' if 'ok' in out and 'true' in out else 'FAIL'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
