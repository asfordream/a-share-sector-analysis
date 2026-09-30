#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把「四层技术分析」新版推送文案发到周吉清 bot 私信做人工预览（不上传 HTML、不发链接）。

用途：改版推送格式后，先发预览给用户确认渲染效果，再落到正式自动化。
用法：python3 scripts/preview_tech4.py [hk|a|both]   默认 both
"""
import importlib.util
import json
import os
import subprocess
import sys

A_WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HK_WS = os.environ.get("HK_SECTOR_DIR", "")
UID = os.environ.get("FEISHU_USER_OPEN_ID", "")
LARK = os.environ.get("LARK_CLI", "lark-cli")
ENV = dict(os.environ,
           LARKSUITE_CLI_NO_UPDATE_NOTIFIER="1",
           LARKSUITE_CLI_NO_SKILLS_NOTIFIER="1")

BANNER = ("🧪 **推送格式改版预览 · 新增「四层技术分析」**\n"
          "（数据时点 2026-08-17 收盘；本条为格式预览，非当日正式推送）\n\n")


def send(text, cwd):
    r = subprocess.run([LARK, "im", "+messages-send", "--as", "bot",
                        "--user-id", UID, "--markdown", text],
                       cwd=cwd, env=ENV, capture_output=True, text=True)
    out = (r.stdout + r.stderr).strip()
    ok = '"ok": true' in out or '"code": 0' in out
    return ok, out[:200]


def _load(mod_name, path):
    """按绝对路径加载模块——两个工作区都有 push.py，直接 import 会串模块。"""
    sys.path.insert(0, os.path.dirname(path))
    spec = importlib.util.spec_from_file_location(mod_name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def preview_hk():
    HP = _load("hk_push", os.path.join(HK_WS, "scripts", "push.py"))
    sectors = HP.load_sectors()
    m = HP.by_name(sectors)
    ordered = [m[n] for n in HP.BATCH_ORDER if n in m]
    return BANNER + HP.daily_report_md(ordered, "20260817")


def preview_a():
    AP = _load("a_push_bot_md", os.path.join(A_WS, "scripts", "push_bot_md.py"))
    with open(os.path.join(A_WS, "data", "_summary.json"), encoding="utf-8") as f:
        S = json.load(f)
    return BANNER + AP.build_daily_md(S, "20260817")


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "both"
    jobs = []
    if which in ("hk", "both"):
        jobs.append(("港股2板块", preview_hk(), HK_WS))
    if which in ("a", "both"):
        jobs.append(("A股11板块", preview_a(), A_WS))
    rc = 0
    for tag, md, cwd in jobs:
        ok, out = send(md, cwd)
        print(f"{'OK  ' if ok else 'FAIL'} {tag} preview  ({len(md)} 字)"
              + ("" if ok else f"  {out}"))
        if not ok:
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
