#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reconcile today's 20260806 chat to the NEW push model:
- keep all 10 HTML file messages
- recall the 10 per-sector "【N/10 ...】" markdown posts + the old daily-report card
- send 1 fresh "10板块深度分析日报" card (reuses push.daily_report_card)

Reuses functions from push.py so the card is identical to future batch runs.
"""
import json
import os
import subprocess
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from push import (WS, UID, LARK, ENV, run, send_card, load_sectors,
                  daily_report_card, BATCH_ORDER)

CHAT = os.environ.get("FEISHU_CHAT_ID", "")
CUR_CARD = os.environ.get("FEISHU_MSG_CUR_CARD", "")  # current 日报 card (to replace)


def recall(mid):
    rc, out = run([LARK, "im", "messages", "delete", "--as", "bot",
                   "--message-id", mid, "--yes"])
    ok = '"ok": true' in out or '"code":0' in out
    print(f"recall {mid}: rc={rc} {'OK' if ok else 'CHECK ' + out[:80]}")
    return ok


def main():
    # 1) find per-sector posts to recall
    r = subprocess.run(
        [LARK, "im", "+chat-messages-list", "--as", "bot", "--chat-id", CHAT,
         "--page-size", "45", "--order", "desc", "--format", "json"],
        cwd=WS, env=ENV, capture_output=True, text=True)
    data = json.loads(r.stdout)
    per_ids = []
    for m in data["data"]["messages"]:
        c = m.get("content", "")
        if m["msg_type"] == "post" and ("/10 " in c or "/10　" in c) and "【" in c:
            per_ids.append(m["message_id"])
    print(f"found {len(per_ids)} per-sector posts to recall")

    # 2) recall per-sector posts + old card
    for mid in per_ids:
        recall(mid)
    recall(CUR_CARD)

    # 3) send fresh daily-report card
    sectors = load_sectors()
    bmap = {s["name"]: s for s in sectors}
    ordered = [bmap[n] for n in BATCH_ORDER if n in bmap]
    rundate = datetime.now().strftime("%Y%m%d")
    rc, out = send_card(daily_report_card(ordered, rundate))
    ok = rc == 0 and '"ok": true' in out
    print(f"send daily report card: rc={rc} {'OK' if ok else 'FAIL ' + out[:160]}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
