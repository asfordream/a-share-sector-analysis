#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Re-send the 10-sector aggregate summary with rating + color emphasis.
- 加码/持有 -> red, 观察 -> green (per user instruction)
- recall the previous aggregate (FEISHU_MSG_OLD_AGG), then send the enhanced one.
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
OLD_AGG = os.environ.get("FEISHU_MSG_OLD_AGG", "")


def run(args):
    r = subprocess.run(args, cwd=WS, env=ENV, capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()


def color_of(rating):
    return "red" if rating in ("加码", "持有") else "green"


def main():
    with open(os.path.join(WS, "data", "_summary.json"), encoding="utf-8") as f:
        sectors = json.load(f)

    md = "📊 **研股股·10板块深度分析日报（20260806）**\n\n"
    for i, s in enumerate(sectors, 1):
        c = color_of(s["rating"])
        md += (f"{i}. <font color=\"{c}\">【{s['rating']}】</font>{s['name']}｜"
               f"{s['position']}｜落后补涨：{s['lag']}\n")
    md += ("\n<font color=\"red\">加码</font>/<font color=\"red\">持有</font> = 红（积极）　"
           "<font color=\"green\">观察</font> = 绿（观望）\n"
           "本报告仅供研究参考，不构成个人投资建议")

    # 1) recall old aggregate
    rc, out = run([LARK, "im", "messages", "delete", "--as", "bot",
                   "--message-id", OLD_AGG, "--yes"])
    print(f"recall old aggregate: rc={rc} {'OK' if 'ok' in out and 'true' in out else 'CHECK'} -> {out[:120]}")

    # 2) send enhanced aggregate
    rc, out = run([LARK, "im", "+messages-send", "--as", "bot",
                   "--user-id", UID, "--markdown", md])
    ok = rc == 0 and '"ok": true' in out
    print(f"send enhanced aggregate: rc={rc} {'OK' if ok else 'FAIL'} -> {out[:120]}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
