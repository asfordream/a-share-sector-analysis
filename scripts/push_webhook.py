#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""飞书自定义机器人 webhook 推送（外部群「小韭菜」专用，不走 Open Platform app）。

用法：
  python3 push_webhook.py            # 发 11 板块日报 interactive 卡片（核心结论）到小韭菜群
  python3 push_webhook.py --links    # 额外把 11 个 HTML 报告上传 bot 云盘，发一条"报告链接汇总"卡片

webhook 地址硬编码（用户提供）。自定义机器人消息体：{"msg_type":"interactive","card":{...}}
外部群自定义机器人不直接支持本地文件附件，故完整 HTML 走云盘链接（--links）。
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from urllib.request import Request, urlopen

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tech4  # noqa: E402  四层技术面体检 + 评级×技术面裁决（两段式短标签）

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEBHOOK = os.environ.get("FEISHU_WEBHOOK", "")
LARK = os.environ.get("LARK_CLI", "lark-cli")
ENV = dict(os.environ,
           LARKSUITE_CLI_NO_UPDATE_NOTIFIER="1",
           LARKSUITE_CLI_NO_SKILLS_NOTIFIER="1")
# 今日云盘文件夹（首次手动创建；生产可改为按日期自动建）
FOLDER_TOKEN = os.environ.get("FEISHU_FOLDER_TOKEN", "")


def color_of(rating):
    return "red" if rating in ("加码", "加仓") else ("yellow" if rating == "持有" else "green")


EMOJI = {"加码": "🔴", "加仓": "🔴", "持有": "🟡", "观察": "🟢", "减仓": "🟢",
         "清仓": "🟢", "等待证据": "🟢", "对冲": "🟢", "放弃": "🟢",
         "重新评估": "🟢", "观察名单": "🟢"}


def emoji_of(rating):
    # 颜色强化只用 emoji 圆点，严禁 <font>/<color>（飞书 markdown 会原样显示，已踩坑）
    return EMOJI.get(rating, "🟢")


# 季度技术面着色：偏强=红 / 偏弱=绿 / 中性(共振)=黄（用户指定）
QB_EMOJI = {"偏强": "🔴", "偏弱": "🟢", "中性": "🟡"}


def qb_emoji(state):
    return QB_EMOJI.get(state, "🟡")  # 缺省按中性(黄)处理


def color_lag(lag_txt):
    """落后补涨文本逐段着色：正% 🔴 / 负% 🟢。"""
    if not lag_txt or "无" in lag_txt:
        return lag_txt
    parts = [p.strip() for p in lag_txt.split("/")]
    out = []
    for p in parts:
        m = re.search(r"([+-]?\d+(?:\.\d+)?%)", p)
        neg = m and m.group(1).startswith("-")
        out.append(f"🔵{'🟢' if neg else '🔴'} {p}")
    return " / ".join(out)


# 量能硬门槛（固定格式）：仅 强(≥75)/中(≥40) 进入推送；弱(<40) 剔除
PASS_VOL_GRADES = ("强", "中")


def cand_text(cands):
    """回抽确认候选 → 名称(距MA20%)。仅保留量能评分 强/中 且 确认态==已确认
    （量能硬门槛 + 确认态门槛，2026-08-27 用户拍板）。"""
    if not cands:
        return "无（板块个股普遍已站上MA20）"
    kept = [c for c in cands
            if c.get("volGrade") in PASS_VOL_GRADES and c.get("confirm") == "已确认"]
    if not kept:
        return "无（回抽确认候选暂无量能强/中且已确认的标的）"
    return " / ".join(f"🔵{c['name']}({c['distMa20']:+.2f}%)" for c in kept)


def mup_text(mups):
    """表4 主升浪买点区 → 名称(距MA20%, 近20日%, 量能)。无则提示。

    与回抽确认同口径：仅保留量能 强/中 且 确认态==已确认（2026-08-27 用户拍板）。
    """
    kept = [c for c in (mups or []) if c.get("volGrade") in PASS_VOL_GRADES
            and c.get("confirm") == "已确认"]
    if not kept:
        return "无（板块未现已确认的主升浪买点区标的）"
    return " / ".join(
        f"🔵{c['name']}(距MA20{c['distMa20']:+.2f}%, 近20日{c['chg20d']:+.2f}%, 量能{c['volGrade']})"
        for c in kept)


def _plain_code(code):
    """去交易所前缀：sh/sz/bj → 纯 6 位代码。"""
    code = (code or "").strip()
    for p in ("sh", "sz", "bj"):
        if code[:2].lower() == p:
            return code[2:]
    return code


def collect_codes(sectors):
    """候选代码汇总（与 Step H 跟踪表同口径，2026-08-28 用户拍板）。

    入选板块 = 裁决 emoji==🔴 ∪ 格局含「反弹可参与」∪「结构已立」∪「加码・匹配执行」
    （build_track_table.py 同源）；仅确认态==已确认；返回 (code, name) 元组、6 位无前缀代码，
    回抽确认/主升浪买点区 各自跨板块去重、空格分隔，每项「code name」。"""
    cand_codes, mup_codes = [], []
    seen_c, seen_m = set(), set()
    for s in sectors:
        vt, vemo = sector_verdict(s)
        in_scope = ((vemo == "🔴") or ("反弹可参与" in vt) or ("结构已立" in vt)
                    or (vt.startswith("加码") and "匹配执行" in vt))
        if not in_scope:
            continue
        for c in s.get("cands", []):
            if c.get("confirm") == "已确认":
                code = _plain_code(c.get("code"))
                if code and code not in seen_c:
                    seen_c.add(code)
                    cand_codes.append((code, c.get("name") or ""))
        for c in s.get("mups", []):
            if c.get("confirm") == "已确认":
                code = _plain_code(c.get("code"))
                if code and code not in seen_m:
                    seen_m.add(code)
                    mup_codes.append((code, c.get("name") or ""))
    return cand_codes, mup_codes


def sector_vtype(s):
    """取该板块四层裁决短标签（两段式：加码·双强共振/持有·等回踩/观察·可上调/清仓·反弹卖…）。"""
    U, sq = tech4.load_universe(f"{WS}/data", s["name"])
    t4 = tech4.compute(U, sq, s.get("rating"))
    return t4["verdict_type"] if t4 else "MISSING"


def sector_verdict(s):
    """取该板块四层裁决 (短标签, emoji)。emoji 按「评级×技术面裁决逻辑总表」emoji 列，
    头条圆点用它而非评级色；人工评价行/汇总行仍用评级色。"""
    U, sq = tech4.load_universe(f"{WS}/data", s["name"])
    t4 = tech4.compute(U, sq, s.get("rating"))
    if not t4:
        return "MISSING", "🟡"
    return t4["verdict_type"], t4["conclusion_emo"]


def load_sectors():
    with open(f"{WS}/data/_summary.json", encoding="utf-8") as f:
        return json.load(f)


def build_summary_card(sectors, rd):
    els = []
    # 候选代码汇总（2026-08-28 用户要求：标题之后、板块分析之前；与跟踪表同口径、无 sz/sh 前缀）
    cand_codes, mup_codes = collect_codes(sectors)
    code_parts = []
    if cand_codes:
        code_parts.append("　　　　回抽确认：")
        code_parts.append("　　　　　　股票编号：" + " ".join(c for c, n in cand_codes))
        code_parts.append("　　　　　　股票名：" + " ".join(n for c, n in cand_codes))
    if mup_codes:
        code_parts.append("　　　　主升浪买点区：")
        code_parts.append("　　　　　　股票编号：" + " ".join(c for c, n in mup_codes))
        code_parts.append("　　　　　　股票名：" + " ".join(n for c, n in mup_codes))
    if code_parts:
        els.append({
            "tag": "div",
            "text": {"tag": "lark_md",
                     "content": "　　<b>候选代码汇总（已确认）：</b>\n" + "\n".join(code_parts)}
        })
    for i, s in enumerate(sectors, 1):
        e = emoji_of(s["rating"])
        vt, vemo = sector_verdict(s)
        # 主行
        els.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (f"{i}. {vemo} <b>【{vt}】{s['name']}</b>｜<b>{s['position']}</b>")
            }
        })
        # 子行1：人工评价（评级 + emoji）
        els.append({
            "tag": "div",
            "text": {"tag": "lark_md",
                     "content": f"　　<b>人工评价</b>：{emoji_of(s['rating'])} {s['rating']}"}
        })
        # 子行2：个股分析分组标题
        els.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": "　　<b>个股分析：</b>"}
        })
        # 子行3：落后补涨（带涨跌色）
        els.append({
            "tag": "div",
            "text": {"tag": "lark_md",
                     "content": f"　　　　落后补涨：{color_lag(s.get('lag', ''))}"}
        })
        # 子行4：回抽确认（名称+距MA20%）
        els.append({
            "tag": "div",
            "text": {"tag": "lark_md",
                     "content": f"　　　　回抽确认：{cand_text(s.get('cands', []))}"}
        })
        # 子行5：主升浪买点区（表4，名称+距MA20%+近20日%+量能）
        els.append({
            "tag": "div",
            "text": {"tag": "lark_md",
                     "content": f"　　　　主升浪买点区：{mup_text(s.get('mups', []))}"}
        })
        # 子行6：季度技术面（人工评级为主，季度信号为辅，按强弱着色）
        if s.get("qb_note"):
            els.append({
                "tag": "div",
                "text": {"tag": "lark_md",
                         "content": f"　　季度技术面：{qb_emoji(s.get('qb_state'))} {s['qb_note']}"}
            })
    els.append({"tag": "hr"})
    jia = [s["name"] for s in sectors if s["rating"] in ("加码", "加仓")]
    chi = [s["name"] for s in sectors if s["rating"] == "持有"]
    guan = [s["name"] for s in sectors if s["rating"] in ("观察", "减仓", "清仓", "等待证据")]
    summary_parts = []
    if jia:
        summary_parts.append(f"🔴 加码：{', '.join(jia)}")
    if chi:
        summary_parts.append(f"🟡 持有：{', '.join(chi)}")
    if guan:
        summary_parts.append(f"🟢 观察：{', '.join(guan)}")
    els.append({
        "tag": "div",
        "text": {
            "tag": "lark_md",
            "content": "　".join(summary_parts)
        }
    })
    els.append({
        "tag": "note",
        "elements": [{"tag": "plain_text",
                      "content": "本报告仅供研究参考，不构成个人投资建议"}]
    })
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text",
                      "content": f"📊 研股股·A股11板块深度分析日报（{rd}）"}
        },
        "elements": els
    }


def build_links_card(sectors, rd, links):
    """links: {name: url}"""
    els = [{
        "tag": "div",
        "text": {"tag": "lark_md",
                 "content": "点击各板块链接查看完整 HTML 深度分析报告（飞书登录可见）："}
    }]
    for i, s in enumerate(sectors, 1):
        e = emoji_of(s["rating"])
        url = links.get(s["name"], "")
        vt, vemo = sector_verdict(s)
        line = (f"{i}. {vemo} 【{vt}】<b>{s['name']}</b>｜[完整报告]({url})")
        els.append({"tag": "div", "text": {"tag": "lark_md", "content": line}})
    els.append({
        "tag": "note",
        "elements": [{"tag": "plain_text",
                      "content": "本报告仅供研究参考，不构成个人投资建议"}]
    })
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "green",
            "title": {"tag": "plain_text",
                      "content": f"📎 研股股·A股11板块深度分析报告链接（{rd}）"}
        },
        "elements": els
    }


def post_card(card):
    body = json.dumps({"msg_type": "interactive", "card": card},
                      ensure_ascii=False).encode("utf-8")
    req = Request(WEBHOOK, data=body,
                  headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=30) as r:
        return r.read().decode()


PUBLIC_DATA = '{"external_access":true,"link_share_entity":"anyone_readable","security_entity":"anyone_can_view","share_entity":"only_full_access"}'


def lark_upload(rel_path):
    """上传本地相对路径文件到 bot 云盘 folder，返回 (url, token)。失败 ('', '')。"""
    args = [LARK, "drive", "+upload", "--as", "bot",
            "--file", rel_path, "--folder-token", FOLDER_TOKEN, "--format", "json"]
    r = subprocess.run(args, cwd=WS, env=ENV, capture_output=True, text=True)
    out = (r.stdout + r.stderr).strip()
    m = re.search(r'\{.*\}', out, re.DOTALL)
    if not m:
        return "", ""
    try:
        d = json.loads(m.group(0))
        data = d.get("data", {})
        return data.get("url", ""), data.get("file_token", "")
    except Exception:
        return "", ""


def lark_open_public(token):
    """把单个云盘文件设为「外部链接可读」（适配外部群）。返回是否成功。"""
    if not token:
        return False
    args = [LARK, "drive", "permission.public", "patch",
            "--token", token, "--type", "file", "--as", "bot",
            "--data", PUBLIC_DATA, "--yes", "--format", "json"]
    r = subprocess.run(args, env=ENV, capture_output=True, text=True)
    try:
        return json.loads(r.stdout).get("ok", False)
    except Exception:
        return False


LINKS_CACHE = os.path.join(WS, "data", "_links.json")


def upload_all(sectors):
    # 若同一轮 push_bot_md.py 已上传过（当天缓存且覆盖全部板块），直接复用，避免重复上传/OOM
    if os.path.exists(LINKS_CACHE):
        try:
            cache = json.load(open(LINKS_CACHE, encoding="utf-8"))
            fresh = (datetime.now().timestamp() - os.path.getmtime(LINKS_CACHE)) < 6 * 3600
            if fresh and all(cache.get(s["name"]) for s in sectors):
                print(f"  reuse links cache ({len(cache)} files)")
                return {s["name"]: cache[s["name"]] for s in sectors}
        except Exception:
            pass
    links = {}
    for s in sectors:
        rel = os.path.basename(s["path"])
        url, token = lark_upload(rel)
        if url:
            lark_open_public(token)  # 上传即开外部可读，外部群成员可点开
        links[s["name"]] = url
        print(f"  uploaded+public {s['name']} -> {url[:50]}..." if url else f"  FAIL {s['name']}")
    return links


if __name__ == "__main__":
    sectors = load_sectors()
    rd = os.environ.get("REPORT_DATE") or datetime.now().strftime("%Y%m%d")
    if "--sector" in sys.argv:
        name = sys.argv[sys.argv.index("--sector") + 1]
        sectors = [s for s in sectors if s["name"] == name]
        if not sectors:
            print(f"SECTOR NOT FOUND: {name}")
            sys.exit(2)
    if "--links-only" in sys.argv:
        # 仅补发报告链接卡片（结论卡片已存在时用）
        links = upload_all(sectors)
        print("links card:", post_card(build_links_card(sectors, rd, links)))
    elif "--links" in sys.argv:
        # 完整日报：结论卡片 + 报告链接卡片
        print("summary card:", post_card(build_summary_card(sectors, rd)))
        links = upload_all(sectors)
        print("links card:", post_card(build_links_card(sectors, rd, links)))
    else:
        # 仅核心结论卡片
        print("summary card:", post_card(build_summary_card(sectors, rd)))
