#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""步骤 D：推送「周吉清 bot」私信（两段式 markdown，严禁 interactive 卡片）。

流程：
  1) 把 data/_summary.json 里全部板块 HTML 上传飞书云盘（分批 ≤5，规避 lark-cli OOM exit 137），
     并逐文件开「外部链接可读」，拿到 URL。
  2) 消息1：日报 markdown（评级 + 一句话定位 + 落后补涨 + 回抽确认）。
  3) 消息2：链接 markdown（每行 [完整报告](URL)）。

用法：
  python3 scripts/push_bot_md.py                # 上传 + 发两条
  python3 scripts/push_bot_md.py --links-file X # 复用已有链接 json（{name: url}），跳过上传

注：lark-cli --file / --folder 上传只接受 CWD 相对路径，故 cwd 固定为工作区根目录。
"""
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tech4  # noqa: E402  四层技术面体检（动能/结构/量能/位置）+ 评级裁决结论

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UID = os.environ.get("FEISHU_USER_OPEN_ID", "")
LARK = os.environ.get("LARK_CLI", "lark-cli")
ENV = dict(os.environ,
           LARKSUITE_CLI_NO_UPDATE_NOTIFIER="1",
           LARKSUITE_CLI_NO_SKILLS_NOTIFIER="1")
FOLDER_TOKEN = os.environ.get("FEISHU_FOLDER_TOKEN", "")
BATCH = 5
LINKS_CACHE = os.path.join(WS, "data", "_links.json")

PUBLIC_DATA = ('{"external_access":true,"link_share_entity":"anyone_readable",'
               '"security_entity":"anyone_can_view","share_entity":"only_full_access"}')

# 颜色强化只用 emoji 圆点，严禁 <font>/<color>（飞书 markdown 原样显示，已踩坑）
EMOJI = {"加码": "🔴", "加仓": "🔴", "持有": "🟡", "观察": "🟢", "减仓": "🟢",
         "清仓": "🟢", "等待证据": "🟢", "对冲": "🟢", "放弃": "🟢",
         "重新评估": "🟢", "观察名单": "🟢"}


def emoji_of(rating):
    return EMOJI.get(rating, "🟢")


# 季度技术面着色：偏强=红 / 偏弱=绿 / 中性(共振)=黄（用户指定）
QB_EMOJI = {"偏强": "🔴", "偏弱": "🟢", "中性": "🟡"}


def qb_emoji(state):
    return QB_EMOJI.get(state, "🟡")  # 缺省按中性(黄)处理


def color_lag(lag_txt):
    """落后补涨逐段着色：正% 🔴 / 负% 🟢。"""
    if not lag_txt or "无" in lag_txt:
        return lag_txt or "无"
    out = []
    for p in [x.strip() for x in lag_txt.split("/")]:
        m = re.search(r"([+-]?\d+(?:\.\d+)?%)", p)
        neg = bool(m and m.group(1).startswith("-"))
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

    与回抽确认同口径：仅保留量能 强/中 且 确认态==已确认（量能硬门槛 + 确认态门槛，
    2026-08-27 用户拍板）。
    """
    mups = [c for c in (mups or []) if c.get("volGrade") in PASS_VOL_GRADES
            and c.get("confirm") == "已确认"]
    if not mups:
        return "无（板块未现已确认的主升浪买点区标的）"
    return " / ".join(
        f"🔵{c['name']}(距MA20{c['distMa20']:+.2f}%, 近20日{c['chg20d']:+.2f}%, 量能{c['volGrade']})"
        for c in mups)


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


def tech_block(s):
    """四层技术分析块（动能/结构/量能/位置 + 评级裁决结论），返回多行字符串。

    取代原「季度技术面」单行：结构层已含季线多头占比，结论行给出评级裁决。
    """
    U, sq = tech4.load_universe(os.path.join(WS, "data"), s["name"])
    lines = tech4.render_lines(tech4.compute(U, sq, s.get("rating")))
    return "".join(x + "\n" for x in lines)


def sector_vtype(s):
    """取该板块四层裁决短标签（双强共振/健康等回踩/破位预警…），供头条括号使用。"""
    U, sq = tech4.load_universe(os.path.join(WS, "data"), s["name"])
    t4 = tech4.compute(U, sq, s.get("rating"))
    return t4["verdict_type"] if t4 else "MISSING"


def sector_verdict(s):
    """取该板块四层裁决 (短标签, emoji)。emoji 按「评级×技术面裁决逻辑总表」的 emoji 列
    （如 加码・健康等回踩=🟡、持有・破位预警=🟢、观察・可上调=🔴、清仓・反弹卖=🟢），
    头条圆点用它而非评级色；人工评价行/汇总行仍用评级色。"""
    U, sq = tech4.load_universe(os.path.join(WS, "data"), s["name"])
    t4 = tech4.compute(U, sq, s.get("rating"))
    if not t4:
        return "MISSING", "🟡"
    return t4["verdict_type"], t4["conclusion_emo"]


def load_sectors():
    with open(os.path.join(WS, "data", "_summary.json"), encoding="utf-8") as f:
        return json.load(f)


def lark_upload(rel_path):
    args = [LARK, "drive", "+upload", "--as", "bot", "--file", rel_path,
            "--folder-token", FOLDER_TOKEN, "--format", "json"]
    r = subprocess.run(args, cwd=WS, env=ENV, capture_output=True, text=True)
    out = (r.stdout + r.stderr).strip()
    m = re.search(r"\{.*\}", out, re.DOTALL)
    if not m:
        return "", "", out[:160]
    try:
        d = json.loads(m.group(0)).get("data", {})
        return d.get("url", ""), d.get("file_token", ""), ""
    except Exception as e:  # noqa
        return "", "", f"parse:{e}"


def lark_open_public(token):
    if not token:
        return False
    args = [LARK, "drive", "permission.public", "patch", "--token", token,
            "--type", "file", "--as", "bot", "--data", PUBLIC_DATA,
            "--yes", "--format", "json"]
    r = subprocess.run(args, env=ENV, capture_output=True, text=True)
    try:
        return json.loads(r.stdout).get("ok", False)
    except Exception:
        return False


def upload_all(sectors):
    links, fails = {}, []
    for i in range(0, len(sectors), BATCH):
        chunk = sectors[i:i + BATCH]
        print(f"-- batch {i // BATCH + 1} ({len(chunk)} files)")
        for s in chunk:
            rel = os.path.basename(s["path"])
            url, token, err = lark_upload(rel)
            if url:
                lark_open_public(token)
                links[s["name"]] = url
                print(f"  OK   {s['name']} -> {url[:56]}")
            else:
                fails.append(s["name"])
                links[s["name"]] = ""
                print(f"  FAIL {s['name']} {err}")
        time.sleep(2)  # 批间歇，规避 lark-cli 连续大文件上传 OOM
    with open(LINKS_CACHE, "w", encoding="utf-8") as f:
        json.dump(links, f, ensure_ascii=False, indent=1)
    return links, fails


def send_md(text):
    args = [LARK, "im", "+messages-send", "--as", "bot",
            "--user-id", UID, "--markdown", text]
    r = subprocess.run(args, cwd=WS, env=ENV, capture_output=True, text=True)
    out = (r.stdout + r.stderr).strip()
    return ('"ok": true' in out or '"code": 0' in out), out[:200]


def build_daily_md(sectors, rd):
    md = f"📊 **研股股·A股11板块深度分析日报（{rd}）**\n\n"
    # 候选代码汇总（2026-08-28 用户要求：标题之后、板块分析之前；与跟踪表同口径、无 sz/sh 前缀）
    cand_codes, mup_codes = collect_codes(sectors)
    if cand_codes or mup_codes:
        md += "　　**候选代码汇总（已确认）**："
        if cand_codes:
            md += "\n　　　　回抽确认："
            md += "\n　　　　　　股票编号：" + " ".join(c for c, n in cand_codes)
            md += "\n　　　　　　股票名：" + " ".join(n for c, n in cand_codes)
        if mup_codes:
            md += "\n　　　　主升浪买点区："
            md += "\n　　　　　　股票编号：" + " ".join(c for c, n in mup_codes)
            md += "\n　　　　　　股票名：" + " ".join(n for c, n in mup_codes)
        md += "\n\n"
    for i, s in enumerate(sectors, 1):
        vt, vemo = sector_verdict(s)
        md += f"{i}. {vemo} **【{vt}】{s['name']}**｜**{s['position']}**\n"
        md += f"　　**人工评价**：{emoji_of(s['rating'])} {s['rating']}\n"
        md += tech_block(s)
        md += "　　**个股分析：**\n"
        md += f"　　　　落后补涨：{color_lag(s.get('lag', ''))}\n"
        md += f"　　　　回抽确认：{cand_text(s.get('cands', []))}\n"
        md += f"　　　　主升浪买点区：{mup_text(s.get('mups', []))}\n"
    jia = [s["name"] for s in sectors if s["rating"] in ("加码", "加仓")]
    chi = [s["name"] for s in sectors if s["rating"] == "持有"]
    guan = [s["name"] for s in sectors if s["rating"] in ("观察", "减仓", "清仓", "等待证据")]
    if jia:
        md += f"\n🔴 加码：{', '.join(jia)}"
    if chi:
        md += f"\n🟡 持有：{', '.join(chi)}"
    if guan:
        md += f"\n🟢 观察：{', '.join(guan)}"
    md += "\n"
    md += "\n> 数据来源 westock-mcp / WebSearch；量化回抽模型输出，仅供参考，不构成投资建议。"
    return md


def build_links_md(sectors, rd, links):
    md = f"📎 **研股股·A股11板块深度分析报告链接（{rd}）**\n\n"
    md += "点击各板块链接查看完整 HTML 深度分析报告（飞书登录可见）：\n\n"
    for i, s in enumerate(sectors, 1):
        vt, vemo = sector_verdict(s)
        url = links.get(s["name"], "")
        tail = f"[完整报告]({url})" if url else "上传失败 [MISSING]"
        md += f"{i}. {vemo} 【{vt}】{s['name']}｜{tail}\n"
    md += "\n> 数据来源 westock-mcp / WebSearch；量化回抽模型输出，仅供参考，不构成投资建议。"
    return md


def main():
    sectors = load_sectors()
    if "--sector" in sys.argv:
        name = sys.argv[sys.argv.index("--sector") + 1]
        sectors = [s for s in sectors if s["name"] == name]
        if not sectors:
            print(f"SECTOR NOT FOUND: {name}")
            return 2
    rd = os.environ.get("REPORT_DATE") or datetime.now().strftime("%Y%m%d")
    fails = []
    if "--links-file" in sys.argv:
        p = sys.argv[sys.argv.index("--links-file") + 1]
        links = json.load(open(p, encoding="utf-8"))
    else:
        links, fails = upload_all(sectors)

    ok1, out1 = send_md(build_daily_md(sectors, rd))
    print(f"msg1 daily : {'OK' if ok1 else 'FAIL ' + out1}")
    ok2, out2 = send_md(build_links_md(sectors, rd, links))
    print(f"msg2 links : {'OK' if ok2 else 'FAIL ' + out2}")
    if fails:
        print(f"UPLOAD FAILS: {fails}")
    return 0 if (ok1 and ok2 and not fails) else 1


if __name__ == "__main__":
    sys.exit(main())
