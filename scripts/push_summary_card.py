#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Re-send the 10-sector aggregate as a Feishu CARD (interactive) message.
Cards' lark_md element DOES render <font color="...">, unlike post markdown.
Recall the previous broken post aggregate, then send the card.
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
BROKEN_AGG = os.environ.get("FEISHU_MSG_BROKEN_AGG", "")  # the post with literal <font> tags


def run(args):
    r = subprocess.run(args, cwd=WS, env=ENV, capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()


def color_of(rating):
    return "red" if rating in ("加码", "持有") else "green"


def main():
    with open(os.path.join(WS, "data", "_summary.json"), encoding="utf-8") as f:
        sectors = json.load(f)

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

    # 1) recall broken post aggregate
    rc, out = run([LARK, "im", "messages", "delete", "--as", "bot",
                   "--message-id", BROKEN_AGG, "--yes"])
    print(f"recall broken post: rc={rc} {'OK' if 'ok' in out and 'true' in out else 'CHECK'} -> {out[:100]}")

    # 2) send card
    rc, out = run([LARK, "im", "+messages-send", "--as", "bot",
                   "--user-id", UID, "--content", json.dumps(card, ensure_ascii=False),
                   "--msg-type", "interactive"])
    ok = rc == 0 and '"ok": true' in out
    print(f"send card aggregate: rc={rc} {'OK' if ok else 'FAIL'} -> {out[:160]}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
