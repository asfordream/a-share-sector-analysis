#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A股 11 板块自动化「独立看门狗」（2026-09-29 用户需求）。

背景：2026-09-28 主任务按时触发，但会话首个模型请求即被 429 限流拒绝
（`429 queue.full` / category=quota / attempt=1/1）→ 0 工具调用、0 产物、0 告警，
用户次日才发现「昨天没跑出来」。本脚本用于补上这个「静默失败」盲区。

设计原则：**只看文件系统事实，不依赖主任务的任何运行时接口**。
判定四项（任一异常即告警）：
  1. data/_summary.json            mtime 是否今日   ← 主任务 C 步（11 板块汇总）
  2. 当日 HTML 报告数              <板块>板块深度分析_<YYYYMMDD>.html
  3. A股板块候选跟踪表.xlsx        mtime 是否今日   ← Step H
  4. data/_g_final.json            mtime 是否今日   ← Step G

行为：
  - 全部正常 → 静默退出（不发消息，避免每日打扰）
  - 任一异常 → 发飞书私信告警；同一天只发一次（去重文件 data/_watchdog_last_alert）
  - 通道：主 = lark-cli 私信周吉清 bot；失败 → 降级 → 小韭菜群 webhook（文案标注降级）

用法：
  python3 scripts/watchdog_ashare.py                    # 正式判定（异常则告警）
  python3 scripts/watchdog_ashare.py --dry-run          # 只判定、不发消息
  python3 scripts/watchdog_ashare.py --selftest         # 通道自检（发一条测试消息，不写去重）
  python3 scripts/watchdog_ashare.py --date 20260925    # 用指定日期当「今天」（调试/回测）
  python3 scripts/watchdog_ashare.py --force            # 忽略当日去重，强制重发
  python3 scripts/watchdog_ashare.py --mute-today       # 写入当日静默标记（当日不再告警）

退出码：0 = 正常（含静默成功）；1 = 检出异常（已发或已发过告警）；2 = 脚本自身错误。
"""
import argparse
import glob
import json
import os
import subprocess
import sys
from datetime import date, datetime
from urllib.request import Request, urlopen

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(WS, "data")
SUMMARY = os.path.join(DATA, "_summary.json")
GFINAL = os.path.join(DATA, "_g_final.json")
XLSX = os.path.join(WS, "A股板块候选跟踪表.xlsx")
STATE = os.path.join(DATA, "_watchdog_last_alert")
MUTE = os.path.join(DATA, "_watchdog_mute")
LOG_DIR = os.path.expanduser("~/.workbuddy/logs")

WEBHOOK = os.environ.get("FEISHU_WEBHOOK", "")
LARK = os.environ.get("LARK_CLI", "lark-cli")
UID = os.environ.get("FEISHU_USER_OPEN_ID", "")  # 周吉清 bot 私信
ENV = dict(os.environ,
           LARKSUITE_CLI_NO_UPDATE_NOTIFIER="1",
           LARKSUITE_CLI_NO_SKILLS_NOTIFIER="1")
EXPECTED_SECTORS = 11  # 与自动化清单一致（2026-09-23 起 11 板块常驻）


def mtime(p):
    """返回文件 mtime（datetime）或 None。"""
    try:
        return datetime.fromtimestamp(os.path.getmtime(p))
    except OSError:
        return None


def stamp(today):
    """日期串 YYYYMMDD → 带点的展示串 YYYY-MM-DD。"""
    return f"{today[:4]}-{today[4:6]}-{today[6:]}"


def check(today):
    """核心判定。返回 (ok, lines, verdict) —— lines 为逐项体检明细，verdict 为一句结论。"""
    lines, bad = [], []

    # 1) data/_summary.json
    t = mtime(SUMMARY)
    if t is None:
        lines.append("❌ data/_summary.json：**不存在**")
        bad.append("summary")
    elif t.strftime("%Y%m%d") != today:
        lines.append(f"❌ data/_summary.json：mtime {t:%Y-%m-%d %H:%M}（非今日）")
        bad.append("summary")
    else:
        lines.append(f"✅ data/_summary.json：mtime {t:%Y-%m-%d %H:%M}")

    # 2) 当日 HTML 报告（期望板块数优先取 _summary.json 的板块条数）
    expect = EXPECTED_SECTORS
    names = []
    try:
        S = json.load(open(SUMMARY, encoding="utf-8"))
        if isinstance(S, list) and S:
            names = [s.get("name") for s in S if s.get("name")]
            expect = len(names)
    except Exception:
        S = None
    have = [n for n in names
            if os.path.exists(os.path.join(WS, f"{n}板块深度分析_{today}.html"))]
    if names:
        miss = [n for n in names if n not in have]
        if len(have) < expect:
            lines.append(f"❌ 当日 HTML 报告：{len(have)}/{expect}（缺：{'、'.join(miss) or '—'}）")
            bad.append("html")
        else:
            lines.append(f"✅ 当日 HTML 报告：{len(have)}/{expect} 全部存在")
    else:
        n = len(glob.glob(os.path.join(WS, f"*板块深度分析_{today}.html")))
        if n < expect:
            lines.append(f"❌ 当日 HTML 报告：glob 命中 {n} 份（期望 ≥{expect}；_summary.json 不可读）")
            bad.append("html")
        else:
            lines.append(f"✅ 当日 HTML 报告：glob 命中 {n} 份")

    # 3) 跟踪表（Step H）
    t = mtime(XLSX)
    if t is None:
        lines.append("❌ A股板块候选跟踪表.xlsx：**不存在**")
        bad.append("track")
    elif t.strftime("%Y%m%d") != today:
        lines.append(f"❌ A股板块候选跟踪表.xlsx：mtime {t:%Y-%m-%d %H:%M}（非今日，Step H 未执行？）")
        bad.append("track")
    else:
        lines.append(f"✅ A股板块候选跟踪表.xlsx：mtime {t:%Y-%m-%d %H:%M}")

    # 4) Step G 候选清单
    t = mtime(GFINAL)
    if t is None or t.strftime("%Y%m%d") != today:
        lines.append(f"⚠️ data/_g_final.json：mtime {t:%Y-%m-%d %H:%M}" if t else "⚠️ data/_g_final.json：**不存在**")
        # Step G 在 N=0（无 🔴 板块）时也可能被跳过/留旧值 → 仅提示，不单独判失败
    else:
        lines.append(f"✅ data/_g_final.json：mtime {t:%Y-%m-%d %H:%M}")

    ok = not bad
    if ok:
        verdict = "当日产物齐备"
    elif "summary" in bad:
        verdict = "**主任务未产出**（全链路未跑通）"
    else:
        verdict = "**主任务产物不完整**（部分步骤未完成）"
    return ok, lines, verdict


def _recent_log_hint(today):
    """给出当日日志目录的定位提示（帮助快速看被拒原因）。"""
    d = f"{today[:4]}-{today[4:6]}-{today[6:]}"
    p = os.path.join(LOG_DIR, d, "007-指数行业分析__*.log")
    hit = sorted(glob.glob(p))
    if hit:
        return f"当日会话日志：`~/.workbuddy/logs/{d}/{os.path.basename(hit[-1])}`（看文件尾部）"
    return f"当日无会话日志文件（{d}）—— 说明任务可能**根本没被调度**，而非执行中失败"


def build_alert(today, lines, verdict):
    return "\n".join([
        f"⚠️ **研股股·A股11板块自动化｜看门狗告警（{stamp(today)}）**",
        "",
        f"**判定**：{verdict}",
        "",
        *[f"　　{l}" for l in lines],
        "",
        "**排除建议**",
        f"　　· {_recent_log_hint(today)}",
        "　　· 常见根因：模型服务 429 限流（2026-09-28 事故：`queue.full`/category=quota，启动 2 秒即被拒、无任何产物）",
        "　　· 若确认漏跑：手动重跑自动化，或直接跑 `scripts/collect.py` → `swing.py` → `charts.py` → `render.py` 补当日报告",
        "",
        "> 本告警由独立看门狗脚本（scripts/watchdog_ashare.py）发出，不依赖主任务链路，仅供参考。",
    ])


def send_lark(text):
    """主通道：lark-cli 私信周吉清 bot。返回 (ok, detail)。"""
    args = [LARK, "im", "+messages-send", "--as", "bot",
            "--user-id", UID, "--markdown", text]
    try:
        r = subprocess.run(args, cwd=WS, env=ENV, capture_output=True, text=True, timeout=90)
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"
    out = (r.stdout + r.stderr).strip()
    return ('"ok": true' in out or '"code": 0' in out), out[:200]


def send_webhook(text):
    """降级通道：小韭菜群自定义机器人 webhook（纯 HTTP，无 CLI 依赖）。"""
    body = json.dumps({"msg_type": "text",
                       "content": {"text": "【研股股·看门狗】\n" + text}}).encode()
    try:
        req = Request(WEBHOOK, data=body, headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=30) as resp:
            out = resp.read().decode()
        return ('"code":0' in out.replace(" ", "") or '"StatusCode":0' in out.replace(" ", "")), out[:200]
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def deliver(text, dry_run=False):
    """发送告警，返回 (通道描述, ok)。"""
    if dry_run:
        print("[dry-run] 不发送。拟发送内容：\n" + "-" * 60 + f"\n{text}\n" + "-" * 60)
        return "dry-run", True
    ok, detail = send_lark(text)
    if ok:
        return "lark-cli 私信周吉清 bot", True
    print(f"  [warn] 主通道失败：{detail}")
    ok2, detail2 = send_webhook("【降级通道】主通道 lark-cli 发送失败\n\n" + text)
    if ok2:
        return "小韭菜群 webhook（降级）", True
    print(f"  [error] 降级通道亦失败：{detail2}")
    return "全部通道失败", False


def _sent_today(today):
    try:
        return open(STATE, encoding="utf-8").read().strip() == today
    except OSError:
        return False


def _mark_sent(today):
    try:
        with open(STATE, "w", encoding="utf-8") as f:
            f.write(today)
    except OSError as e:
        print(f"  [warn] 去重标记写入失败：{e}")


def main():
    ap = argparse.ArgumentParser(description="A股 11 板块自动化独立看门狗")
    ap.add_argument("--dry-run", action="store_true", help="只判定不发送")
    ap.add_argument("--selftest", action="store_true", help="通道自检：发一条测试消息（不写去重）")
    ap.add_argument("--date", help="把指定日期 YYYYMMDD 当作「今天」（调试/回测）")
    ap.add_argument("--force", action="store_true", help="忽略当日去重，强制重发")
    ap.add_argument("--mute-today", action="store_true", help="写入当日静默标记（当日不再告警）")
    a = ap.parse_args()

    today = a.date or date.today().strftime("%Y%m%d")

    if a.mute_today:
        _mark_sent(today)
        print(f"已写入静默标记（{today} 当日不再告警）")
        return 0

    if a.selftest:
        text = "\n".join([
            f"✅ **研股股·A股11板块自动化｜看门狗通道自检（{stamp(today)}）**",
            "",
            "这是一条**通道自检**消息，不是运行告警 —— 收到即证明看门狗告警链路可用。",
            "正式判定每日 15:40 自动执行：产物齐备时静默，异常时才发告警。",
        ])
        ch, ok = deliver(text, a.dry_run)
        print(f"自检发送通道：{ch} | 结果：{'OK' if ok else 'FAILED'}")
        return 0 if ok else 2

    ok, lines, verdict = check(today)
    print(f"看门狗判定（today={today}）：{'正常' if ok else '异常'} — {verdict}")
    for l in lines:
        print("  " + l)

    if ok:
        print("产物齐备，静默退出（不发送任何消息）")
        return 0

    if _sent_today(today) and not a.force:
        print(f"当日（{today}）已告警过，跳过重复发送（--force 可强制重发）")
        return 1

    ch, sent = deliver(build_alert(today, lines, verdict), a.dry_run)
    print(f"告警发送通道：{ch} | 结果：{'OK' if sent else 'FAILED'}")
    if sent and not a.dry_run:
        _mark_sent(today)
    return 1 if sent else 2


if __name__ == "__main__":
    sys.exit(main())
