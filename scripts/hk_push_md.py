#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""港股板块深度分析 · 两段式飞书推送（仅周吉清 bot 私信，不推群）。

格式（当前指令 D 节）：
  消息1 日报卡片：标题「📊 研股股·港股2板块深度分析日报（YYYYMMDD）」
  消息2 报告链接：标题「📎 研股股·港股2板块深度分析报告链接（YYYYMMDD）」
  - 先上传两份 HTML 到飞书云盘拿 URL
  - 仅发 2 条 markdown（先日报后链接），无附件、无 interactive 卡片、无 EdgeOne
  - emoji 圆点着色：🔴 加码/加仓、🟡 持有、🟢 观察/减仓/清仓/等待证据；个股涨🔴跌🟢
  - 严禁 <font>/<color> 等 HTML 标签
"""
import os, sys, json, subprocess
from datetime import datetime

ARCHIVE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OPEN_ID = os.environ.get("FEISHU_USER_OPEN_ID", "")
LARK = os.environ.get("LARK_CLI", "lark-cli")
SUMMARY = os.path.join(ARCHIVE, "data", "_hk_summary.json")

# emoji 圆点映射（评级 → 圆点）
RATING_EMOJI = {
    "加码": "🔴", "加仓": "🔴",
    "持有": "🟡",
    "观察": "🟢", "减仓": "🟢", "清仓": "🟢", "等待证据": "🟢",
}

def rating_emoji(rating):
    for k, v in RATING_EMOJI.items():
        if rating.startswith(k):
            return v
    # 兜底：未知评级用黄
    return "🟡"

def stock_emoji(token):
    # token 形如「天数智芯-8.24%」或「网易+0.19%」
    if "+" in token:
        return "🔴"  # 涨
    if "-" in token:
        return "🟢"  # 跌
    return ""

def color_lag(lag):
    # 把「A-8.24% / B-5.11% / C+0.19%」逐只加 emoji
    parts = [p.strip() for p in lag.split("/")]
    return " / ".join(f"{stock_emoji(p)}{p}" for p in parts)

def env_no_notify():
    e = dict(os.environ)
    e["LARKSUITE_CLI_NO_UPDATE_NOTIFIER"] = "1"
    e["LARKSUITE_CLI_NO_SKILLS_NOTIFIER"] = "1"
    return e

def run(args, cwd=ARCHIVE):
    p = subprocess.run(args, cwd=cwd, env=env_no_notify(),
                       capture_output=True, text=True)
    out = (p.stdout + p.stderr).strip()
    return p.returncode, out

def upload(file_name):
    """上传 HTML 到飞书云盘（--as bot），返回 URL。"""
    args = [LARK, "drive", "+upload", "--as", "bot",
            "--file", file_name, "--name", file_name]
    code, out = run(args)
    if code != 0:
        print(f"[upload FAIL] {file_name} exit={code}\n{out[:500]}")
        return None
    # 解析 URL：优先 -q '.data.url' 的等效解析
    url = None
    try:
        data = json.loads(out)
        url = data.get("data", {}).get("url")
    except Exception:
        pass
    if not url:
        # 退化：正则抓 https 链接
        import re
        m = re.search(r'https?://[^\s"\']+', out)
        if m:
            url = m.group(0)
    if not url:
        print(f"[upload WARN] {file_name} 未解析到 URL:\n{out[:500]}")
    return url

def send_md(title, body):
    content = f"**{title}**\n\n{body}"
    args = [LARK, "im", "+messages-send", "--as", "bot",
            "--user-id", OPEN_ID, "--markdown", content]
    code, out = run(args)
    ok = code == 0
    print(f"[send {'OK' if ok else 'FAIL'}] {title} exit={code} {out[:200]}")
    return ok

def main():
    date_file = datetime.now().strftime("%Y%m%d")
    with open(SUMMARY, encoding="utf-8") as f:
        rows = json.load(f)

    # 1) 上传两份 HTML，记录 板块名→URL
    urls = {}
    for r in rows:
        fname = os.path.basename(r["path"])
        print(f"-- uploading {fname}")
        u = upload(fname)
        urls[r["sector"]] = u
        print(f"   url={u}")

    # 2) 消息1 日报卡片
    lines1 = []
    for i, r in enumerate(rows, 1):
        emoji = rating_emoji(r["rating"])
        lag = color_lag(r["lag"])
        lines1.append(
            f"{i}. {emoji} 【{r['rating']}】港股{r['sector']}｜{r['logic']}｜"
            f"落后补涨：{lag}"
        )
    body1 = "\n".join(lines1)
    body1 += "\n\n> 数据来源 westock-mcp / WebSearch；量化回抽模型输出，仅供参考，不构成投资建议。"
    title1 = f"📊 研股股·港股2板块深度分析日报（{date_file}）"

    # 3) 消息2 报告链接
    lines2 = ["点击各板块链接查看完整 HTML 深度分析报告（飞书登录可见）：", ""]
    for i, r in enumerate(rows, 1):
        emoji = rating_emoji(r["rating"])
        u = urls.get(r["sector"]) or "#"
        lines2.append(
            f"{i}. {emoji} 【{r['rating']}】港股{r['sector']}｜[完整报告]({u})"
        )
    body2 = "\n".join(lines2)
    body2 += "\n\n> 数据来源 westock-mcp / WebSearch；量化回抽模型输出，仅供参考，不构成投资建议。"
    title2 = f"📎 研股股·港股2板块深度分析报告链接（{date_file}）"

    ok1 = send_md(title1, body1)
    ok2 = send_md(title2, body2)

    print("\nDAILY_OK" if ok1 else "\nDAILY_FAIL")
    print("LINKS_OK" if ok2 else "\nLINKS_FAIL")
    sys.exit(0 if (ok1 and ok2) else 1)

if __name__ == "__main__":
    main()
