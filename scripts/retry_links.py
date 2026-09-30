#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""补传 push_bot_md.py 上传失败的板块报告，合并回 data/_links.json，并只重发 msg2 链接消息。
用法: python3 scripts/retry_links.py [--resend-links]
"""
import json
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import push_bot_md as P  # noqa

LINKS = P.LINKS_CACHE


def main():
    sectors = P.load_sectors()
    links = json.load(open(LINKS, encoding="utf-8")) if os.path.exists(LINKS) else {}
    missing = [s for s in sectors if not links.get(s["name"])]
    print(f"待补传 {len(missing)} 个: {[s['name'] for s in missing]}")
    for s in missing:
        rel = os.path.basename(s["path"])
        for attempt in (1, 2, 3):
            url, token, err = P.lark_upload(rel)
            if url:
                P.lark_open_public(token)
                links[s["name"]] = url
                print(f"  OK   {s['name']} (第{attempt}次) -> {url}")
                break
            print(f"  FAIL {s['name']} (第{attempt}次) {err}")
            time.sleep(4)
        time.sleep(3)
    with open(LINKS, "w", encoding="utf-8") as f:
        json.dump(links, f, ensure_ascii=False, indent=1)
    still = [s["name"] for s in sectors if not links.get(s["name"])]
    print(f"仍失败: {still if still else '无'}")

    if "--resend-links" in sys.argv:
        rd = os.environ.get("REPORT_DATE") or datetime.now().strftime("%Y%m%d")
        ok, out = P.send_md(P.build_links_md(sectors, rd, links))
        print(f"msg2 links 重发: {'OK' if ok else 'FAIL ' + out}")
    return 0 if not still else 1


if __name__ == "__main__":
    sys.exit(main())
