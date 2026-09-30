#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""港股板块报告飞书推送：半导体2条 + 互联网2条 + 港股汇总1条。
推送目标：周吉清 bot 私信（固定）。
【注意】小韭菜群仅由 A 股自动化推送，港股不推群（用户 2026-08-07 指定）。
用法：python3 hk_push.py   # 仅私信
"""
import os, subprocess, sys
from datetime import datetime

ARCHIVE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OPEN_ID = os.environ.get("FEISHU_USER_OPEN_ID", "")
LARK = os.environ.get("LARK_CLI", "lark-cli")

# 港股自动化不推群：小韭菜群仅由 A 股自动化推送（用户 2026-08-07 指定）。
# 故此处置空；港股仅发周吉清 bot 私信。
FIXED_GROUPS = {}

DATE = datetime.now().strftime("%Y-%m-%d")
DATE_FILE = datetime.now().strftime("%Y%m%d")

semiconductor_md = f"""【港股半导体】板块深度分析 · {DATE}

📍 一句话定位
港股半导体 = A+H 双重上市的国产芯片核心资产池（代工中芯/华虹 + 设备 ASMPT + 设计兆易/澜起/壁仞/天数智芯）。板块 20 日均跌 −15.4% 后近 5 日强反弹 +7.4%、当日再涨 +1.4%；但距 MA20 中位数仍 −2.98%、14/20（70%）标的仍在 MA20 下方——典型深跌后回抽确认窗口，反弹尚未确认趋势反转。

⭐ 评级：观察 / 持有（回抽确认窗口，未确认反转）

🎯 回抽确认候选（逢回踩分批，站上 MA20 确认后加）
华虹宏力、ASMPT、纳芯微、国民技术、中电华大

📊 多空概要
多：成熟制程涨价进入财务兑现期（华虹全年 ASP +10~15%、1Q26 净利 +458%）；产能满载 99.7% + 客户预付款长约锁定 2027 年 8 英寸产能；Fab9A 3Q26 末达产、4Q26 并表华力微 Fab5；里昂重申中芯/华虹跑赢大市。
空：70% 标的仍破 MA20、20 日均 −15.4%，二次探底风险实在；涨价→毛利率传导待 2Q26 验证（1Q26 毛利率环比持平 13%）；设计端纳芯微/天岳/壁仞/天数智芯/英诺赛科仍亏损靠 PS 定价；小票流动性差。

📌 数据来源：腾讯自选股 westock 盘中快照 {DATE}；财务/中报标 [MISSING]（2Q26 未披露）。"""

internet_md = f"""【港股互联网】板块深度分析 · {DATE}

📍 一句话定位
港股互联网 = 港股市场 AI 含量最高的核心资产池（腾讯/阿里/美团/京东/快手/网易/百度/小米等）。趋势已确认：73% 标的站上 MA20、20 日均涨 +4.6%、距 MA20 中位数 +1.48%；驱动“盈利见底 + AI 从成本项转收入项 + 估值仍处近一年 34% 分位”三重叠加。近 5 日 −1.3% 属上涨后高位整理，非趋势破坏。

⭐ 评级：加码 / 持有（趋势已确认，中报为双击验证窗口）

🎯 落后补涨候选（等 MA5 上穿 MA10 再动）
百度集团、微博、小米集团、名创优品、心动公司、东方甄选

📊 多空概要
多：盈利见底（4 月监管遏制价格战）；AI 从成本项转收入项（Qwen3.8、千问办公公测）；恒生科技 PB 2.65x 处 34% 分位；南向资金持续流入。
空：“交作业”仍是预期（26Q1 头部收入仅温和）；估值修复依赖 8 月中报兑现；外部利率/地缘扰动随时逆转风险偏好。

📌 数据来源：腾讯自选股 westock 盘中快照 {DATE}；估值分位来源中信证券/里昂。"""

summary_md = f"""【港股板块深度分析日报】{DATE}

📌 港股半导体（评级：观察 / 持有 · 回抽确认窗口，未确认反转）
一句话定位：A+H 双重上市的国产芯片核心资产池；20 日均 −15.4% 后反弹，但 70%（14/20）标的仍破 MA20。
回抽确认候选：华虹宏力、ASMPT、纳芯微、国民技术、中电华大。

📌 港股互联网（评级：加码 / 持有 · 趋势已确认，中报为双击验证窗口）
一句话定位：港股 AI 含量最高的核心资产池；73% 站上 MA20、20 日均 +4.6%、距 MA20 中位数 +1.48%。
落后补涨候选：百度集团、微博、小米集团、名创优品、心动公司、东方甄选。

⚠️ 本报告基于盘中快照，仅供研究参考，不构成个人投资建议。"""

files = {
    "半导体": f"港股半导体板块深度分析_{DATE_FILE}.html",
    "互联网": f"港股互联网板块深度分析_{DATE_FILE}.html",
}

# 5 条消息：(类型, 内容) —— md=markdown 文本，file=HTML 附件
MESSAGES = [
    ("md", semiconductor_md),
    ("file", files["半导体"]),
    ("md", internet_md),
    ("file", files["互联网"]),
    ("md", summary_md),
]


def env_with_no_notify():
    e = dict(os.environ)
    e["LARKSUITE_CLI_NO_UPDATE_NOTIFIER"] = "1"
    e["LARKSUITE_CLI_NO_SKILLS_NOTIFIER"] = "1"
    return e


def chat_flag(kw):
    if "user_id" in kw:
        return ["--user-id", kw["user_id"]]
    return ["--chat-id", kw["chat_id"]]


def run(args):
    p = subprocess.run(args, cwd=ARCHIVE, env=env_with_no_notify(),
                      capture_output=True, text=True)
    out = (p.stdout + p.stderr).strip()
    print(f"[exit={p.returncode}] {' '.join(args[:6])} ...")
    if out:
        print("   ", out[:300])
    return p.returncode == 0


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode not in ("all", "group-only"):
        print("usage: hk_push.py [all|group-only]")
        sys.exit(2)

    ok = True
    targets = []
    if mode == "all":
        targets.append({"user_id": OPEN_ID})
    for name, cid in FIXED_GROUPS.items():
        targets.append({"chat_id": cid})
        print(f"  [info] 固定群「{name}」chat_id={cid} 将一并推送。")

    for t in targets:
        label = t.get("user_id", t.get("chat_id"))
        print(f"\n=== 推送目标 {label} (mode={mode}) ===")
        for kind, content in MESSAGES:
            if kind == "md":
                args = [LARK, "im", "+messages-send", "--as", "bot"] + chat_flag(t) + ["--markdown", content]
            else:
                args = [LARK, "im", "+messages-send", "--as", "bot"] + chat_flag(t) + ["--file", content]
            ok &= run(args)

    print("\nALL_OK" if ok else "\nSOME_FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
