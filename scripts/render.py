#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""渲染 10 节板块深度分析 HTML 报告（含 4 张 ECharts）"""
import json, os, sys, html
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tech4  # noqa: E402  四层技术面体检 + 主升浪确认态

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = f"{BASE}/data"
# 运行日动态取当天（避免硬编码导致次日调度沿用旧日期）；
# 可用环境变量 RUNDATE 覆盖，格式 YYYYMMDD（补跑历史用）。
_rd = os.environ.get("RUNDATE") or datetime.now().strftime("%Y%m%d")
RUNDATE = _rd
RUNDATE_H = f"{_rd[:4]}-{_rd[4:6]}-{_rd[6:8]}"
NAMES = ["A股创新药", "算力", "半导体", "存储", "人形机器人", "光通信", "CPO",
         "PCB", "商业航天", "电网设备", "AI应用"]  # 2026-08-18 移除证券/电力/光模块、新增电网设备；2026-08-31 新增 AI应用；2026-09-04 移除宇树科技概念；2026-09-23 移除元件、新增 CPO

# ============ 叙事源统一：读 sector-webapp/data/narratives.json（25 板块，最新人工满血版）============
# 旧 scripts/narratives.py 已于 2026-08-12 彻底移除，JSON 为唯一叙事源（不再有双源矛盾）。
# 适配器把 JSON 新 schema 转成 render.py 消费的旧字段形状，保证自动化头条评级与手动报告完全一致。
NARR_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                         "sector-webapp", "data", "narratives.json")
try:
    RAW = json.load(open(NARR_JSON, encoding="utf-8"))
except Exception:
    RAW = {}

# 短名(NAMES) -> JSON 键 别名映射（NAMES 用旧短名，JSON 用「A股|规范名」）
NAR_KEYS = {
    "A股创新药": "A股|创新药",
    "算力": "A股|AI算力(算力租赁)",
    "半导体": "A股|半导体",
    "存储": "A股|存储芯片",
    "人形机器人": "A股|人形机器人",
    "光通信": "A股|光通信",
    "CPO": "A股|CPO概念",     # 2026-09-23 加入常驻（叙事块已存在）
    "PCB": "A股|PCB",
    "商业航天": "A股|商业航天",
    "电网设备": "A股|电网设备",   # 2026-08-18 加入常驻
    "AI应用": "A股|AI应用",       # 2026-08-31 加入常驻
}
_PROS_ZH = {"policy": "政策导向", "demand": "需求", "price": "价格信号",
            "earn": "业绩兑现", "tam": "TAM/空间", "model": "商业模式"}


def _adapt_json(v, jkey):
    """JSON 新 schema -> render.py 旧字段形状（缺字段置占位，不编造）。"""
    canon = jkey.split("|", 1)[-1] if "|" in jkey else jkey
    chain = [(c.get("layer", ""), c.get("note", ""), c.get("stocks", ""))
             for c in (v.get("chain") or []) if isinstance(c, dict)]
    pros = v.get("prosperity") or {}
    if isinstance(pros, dict):
        prosperity = [(_PROS_ZH.get(k, k), val, "") for k, val in pros.items() if val]
    else:
        prosperity = list(pros)
    cats = v.get("catalysts") or []
    if cats and isinstance(cats[0], str):
        catalysts = [(f"催化{i+1}", c, "偏多") for i, c in enumerate(cats)]
    else:
        catalysts = list(cats)
    competition = v.get("competition") or "（竞争格局与定价权详见第④节核心公司画像，由实时行情体现）"
    return dict(rating=v.get("rating") or "观察",
                rating_state=v.get("state_desc") or "",
                position=v.get("essence") or "",
                label=v.get("label") or canon,
                chain=chain, prosperity=prosperity, competition=competition,
                bull=v.get("bull") or [], bear=v.get("bear") or [],
                catalysts=catalysts, risks=v.get("risks") or [])


def _resolve_key(name):
    if name in NAR_KEYS:
        return NAR_KEYS[name]
    cand = "A股|" + name
    if cand in RAW:
        return cand
    if name.startswith("A股"):
        cand2 = "A股|" + name[2:]
        if cand2 in RAW:
            return cand2
    return None


# 旧 scripts/narratives.py 已彻底移除（2026-08-12）：JSON 为唯一叙事源。
# JSON 缺某板块时不依赖外部文件，直接给安全占位，避免新增板块未补 JSON 时崩溃。
_N_DEFAULT = dict(rating="观察", rating_state="", position="", label="",
                  chain=[], prosperity=[], competition="",
                  bull=[], bear=[], catalysts=[], risks=[])

N = {}
for _nm in NAMES:
    _jk = _resolve_key(_nm)
    if _jk and _jk in RAW:
        N[_nm] = _adapt_json(RAW[_jk], _jk)
    else:
        N[_nm] = dict(_N_DEFAULT, label=_nm)

E = html.escape


def f2(v, suf="", dash="[MISSING]"):
    if v is None:
        return f'<span class="missing">{dash}</span>'
    return f"{v:,.2f}{suf}"


def sign(v, suf="%"):
    if v is None:
        return '<span class="missing">[MISSING]</span>'
    c = "up" if v > 0 else ("down" if v < 0 else "flat")
    return f'<span class="{c}">{v:+.2f}{suf}</span>'


def num(v, d=None):
    try:
        return float(v)
    except Exception:
        return d


def is_main_uptrend(u):
    """主升浪判定（2026-09-02 收紧）：中期多头「且结构仍在生长」+ 近段动量仍正。
    - MA20>MA60 且 MA20>MA10（MA20 仍在 MA10 上方 = 结构在生长，剔除见顶残差）
    - 近20日涨幅≥10% 且 近5日涨幅≥-3%（近段未转跌，避免"前涨后跌"假主升）
    不再仅以 MA20>MA60 这一滞后信号判定，必须与 MA10 同向上行 + 近段动量未翻负。"""
    ma20, ma60, ma10 = u.get("ma20"), u.get("ma60"), u.get("ma10")
    if None in (ma20, ma60, ma10):
        return False
    if not (ma20 > ma60 and ma20 > ma10):
        return False
    if (u.get("chg20d") or 0) < 10:
        return False
    if (u.get("chg5d") or 0) < -3:
        return False
    return True


def _mup_restart(u):
    """主升浪重启确认（2026-09-02）：真实 thrust / 动量结构完好，非一根小阳线。
    两分支各自独立（按用户原口径）：
    - 分支A：MACD 红柱(dif>dea) → 主升浪动量结构完好，回踩即买点区（不要求当日阳线，
      否则会把"主升浪中健康回踩"的票错杀）。数据源未存历史 distMa20，"distMa20 较5日前回升"
      以 MACD 红柱等价表达（动量结构完好 = 回踩在多头框架内）。
    - 分支B：放量比>1.2 且 当日阳线(chg>0) → 真实 breakout thrust。"""
    dif, dea = u.get("dif"), u.get("dea")
    vr = u.get("volRatio")
    chg = u.get("chg")
    macd_red = (dif is not None and dea is not None and dif > dea)
    if macd_red:
        return True
    if (vr is not None and vr > 1.2) and (chg is not None and chg > 0):
        return True
    return False


def classify(u):
    """回抽确认分级"""
    dm, r6 = u.get("distMa20"), u.get("rsi6")
    if dm is None:
        return "无技术信号"
    if dm > 0:
        return "已站上MA20"
    if dm >= -10 and (r6 is None or 32 <= r6 <= 64):
        return "回抽确认候选"
    if dm >= -20:
        return "接近/支撑观察"
    return "未到确认位"


def build(name):
    d = json.load(open(f"{DATA}/{name}.json", encoding="utf-8"))
    ch = json.load(open(f"{DATA}/{name}_chart.json", encoding="utf-8"))
    nar = N[name]
    sq = d["sector_quote"] or {}
    U = d["universe"]

    s_chg = num(sq.get("change_percent"))
    s_20d = num(sq.get("chg_20d"))
    s_60d = num(sq.get("chg_60d"))
    s_ytd = num(sq.get("chg_ytd"))
    s_pe = num(sq.get("pe_ratio"))
    s_pb = num(sq.get("pb_ratio"))

    for u in U:
        u["_cls"] = classify(u)
        # 主升浪买点区标记（独立表4，不抢占回抽确认 _cls，故不改推送口径）
        # 口径（2026-09-02 收紧）：中期多头(MA20>MA60 且 MA20>MA10) + 近20日≥10% 且近5日≥-3%
        #        + 回踩距MA20 -15%~+5%（剔除 +5% 以上追高区）+ 量能强/中
        #        + 重启确认(_mup_restart：MACD红柱+阳线 或 放量比>1.2+阳线)
        # 与 Step G 写自选股完全一致的同一套口径（_summary.json 的 mups 直接复用本标记）。
        u["_mup"] = (is_main_uptrend(u) and u.get("distMa20") is not None
                     and -15 <= u["distMa20"] <= 5
                     and u.get("volGrade") in ("强", "中")
                     and _mup_restart(u))

    # 量能硬门槛（固定格式）：回抽确认候选仅保留 强(≥75)/中(≥40)，弱(<40) 剔除
    cands = sorted([u for u in U if u["_cls"] == "回抽确认候选" and u.get("volGrade") in ("强", "中")],
                   key=lambda x: x["distMa20"])
    near = sorted([u for u in U if u["_cls"] == "接近/支撑观察"], key=lambda x: x["distMa20"])
    deep = sorted([u for u in U if u["_cls"] == "未到确认位"], key=lambda x: x["distMa20"])
    mup = sorted([u for u in U if u.get("_mup")], key=lambda x: x["distMa20"])
    above = sorted([u for u in U if u["_cls"] == "已站上MA20"], key=lambda x: -x["distMa20"])
    # 主升浪确认态标记（2026-08-27 新增）：个股已站上MA20 / 放量比>1.5 或 板块 MA20>MA60
    # 占比≥50% → 已确认（扳机已扣动）；否则 待确认（setup 尚未确认，高假突破风险）。
    # 供 表4 列示 + _summary.mups.confirm + Step G/H 消费（口径见 tech4.main_uptrend_confirm）。
    _bull_ratio = tech4.sector_bull_ratio(U)
    for _u in mup:
        _u["_confirm"] = tech4.main_uptrend_confirm(_u, _bull_ratio)
    # 回抽确认候选「确认态」标记（2026-08-27 用户拍板：板块结构≥50%为前提，再判条件2/3）
    for _u in cands:
        _u["_confirm"] = tech4.pullback_confirm(_u, _bull_ratio)
    core = sorted(U, key=lambda x: -(x["mcap"] or 0))[:12]
    # 落后补涨候选：优先「当日涨跌幅」最弱 3 只（盘中/收盘实时口径）。
    # 盘前/停牌导致全board当日涨跌幅均为 0 时，降级用「距MA20」最弱 3 只并显式标注口径，
    # 避免把 distMa20 当成当日涨跌幅误读（口径混淆已踩坑）。
    _chg = [u for u in U if u.get("chg") is not None]
    _intraday_live = any(abs(u["chg"]) > 1e-9 for u in _chg)
    if _intraday_live:
        lag_basis = "chg"
        lag_top = sorted(_chg, key=lambda x: x["chg"])[:3]
    else:
        lag_basis = "distMa20"
        lag = sorted([u for u in U if u["distMa20"] is not None and u["distMa20"] < 0],
                     key=lambda x: x["distMa20"])
        lag_top = sorted(lag[:10], key=lambda x: -(x["mcap"] or 0))[:3] or lag[:3]

    # ---------- 图表数据 ----------
    ytd_d = ch["ytd"]["dates"]
    ytd_c = ch["ytd"]["close"]
    base0 = ytd_c[0] if ytd_c else 1
    ytd_pct = [round((c / base0 - 1) * 100, 2) for c in ytd_c]

    peers = ch["peers"]
    peer_names = [p["name"] for p in peers]
    peer_ytd = [p["chgYtd"] for p in peers]
    peer_20d = [p["chg20d"] for p in peers]

    val = [u for u in core if u["pe"] and u["pe"] > 0][:12]
    val_names = [u["name"] for u in val]
    val_pe = [round(u["pe"], 1) for u in val]
    val_pb = [round(u["pb"], 2) if u["pb"] else None for u in val]

    dist_src = sorted([u for u in U if u["distMa20"] is not None], key=lambda x: x["distMa20"])
    dist_names = [u["name"] for u in dist_src]
    dist_vals = [u["distMa20"] for u in dist_src]
    dist_colors = ["#c62828" if u in cands else ("#ef9a9a" if u["distMa20"] < 0 else "#78909c") for u in dist_src]

    # 严格确认口径（供飞书推送 / 腾讯自选股「回调买入」分组同步）：
    # 与 HTML 表1「回抽确认候选」完全一致 —— 距MA20 0%~-10%、RSI_6 32~64、量能强/中（不要求 MA5>MA10）。
    # 不再单独收窄 RSI，且不限数量，使推送名单与报告表格口径严格一致。
    def _strict(u):
        dm, r6 = u.get("distMa20"), u.get("rsi6")
        return (dm is not None and -10 <= dm <= 0
                and r6 is not None and 32 <= r6 <= 64
                and u.get("volGrade") in ("强", "中"))

    strict = [u for u in cands if _strict(u)]
    strict_txt = " / ".join(
        f'{E(u["name"])}({u["distMa20"]:+.2f}%，RSI_6 {u["rsi6"]:.0f}，量能{u.get("volScore") if u.get("volScore") is not None else "-"}/{E(u.get("volGrade") or "-")})'
        for u in strict) or '<span class="missing">无（今日无标的同时满足严格条件）</span>'

    # 季度波段技术面（方案C：人工评级为主，季度信号为辅——仅作辅助注记，不覆盖人工评级）
    qb_us = [u for u in U if u.get("ma120") is not None and u.get("ma60") is not None]
    rating_qb = None
    rating_state_qb = None
    if qb_us:
        pct_qb = sum(1 for u in qb_us if u.get("qbUptrend")) / len(qb_us) * 100
        dm60 = [u["distMa60"] for u in qb_us if u.get("distMa60") is not None]
        mean_dm60 = sum(dm60) / len(dm60) if dm60 else 0.0
        dm120 = [u["distMa120"] for u in qb_us if u.get("distMa120") is not None]
        mean_dm120 = sum(dm120) / len(dm120) if dm120 else 0.0
        if mean_dm120 < -20:
            rating_qb = "等待证据"
        elif pct_qb < 30:
            rating_qb = "观察"
        elif mean_dm60 > 12:
            rating_qb = "持有"
        elif -12 <= mean_dm60 <= 0:
            rating_qb = "加码"
        else:
            rating_qb = "持有"
        rating_state_qb = (f"季多头占比{pct_qb:.0f}%，样本均值距MA60 {mean_dm60:+.1f}%、"
                           f"距MA120 {mean_dm120:+.1f}%")
    rating = nar["rating"]            # 人工评级为主（头条）
    rating_state = nar["rating_state"]
    rcls = {"加码": "up", "持有": "flat", "观察": "down"}.get(rating, "flat")
    # 季度映射为辅：仅在季度信号与人工评级背离时给辅助注记（季偏弱=时机未到；季偏强=可加仓；一致=共振）
    qb_note = None
    qb_state = None  # 结构化状态，供推送/HTML 着色：偏强=红 / 偏弱=绿 / 中性(共振)=黄
    QB_EMOJI = {"偏强": "🔴", "偏弱": "🟢", "中性": "🟡"}
    if rating_qb:
        _RANK = {"加码": 3, "加仓": 3, "持有": 2, "观察": 1, "等待证据": 0, "减仓": -1, "清仓": -2}
        _d = _RANK.get(rating_qb, 2) - _RANK.get(rating, 2)
        if _d < 0:
            qb_state = "偏弱"
            qb_note = (f"⚠️ 季度技术面偏弱（{rating_qb}）：{rating_state_qb}，"
                       f"人工「{rating}」但季线未到买点，时机未到")
        elif _d > 0:
            qb_state = "偏强"
            qb_note = (f"季度技术面偏强（{rating_qb}）：{rating_state_qb}，"
                       f"季线共振，回调中可择机加仓")
        else:
            qb_state = "中性"
            qb_note = f"✓ 季度技术面共振（{rating_qb}）：{rating_state_qb}"

    # ---------- PM 七问 ----------
    breadth_neg = len([u for u in U if u["distMa20"] is not None and u["distMa20"] < 0])
    pm7 = [
        ("① 现在处在周期/趋势的什么位置？",
         f"板块指数 {RUNDATE_H} 收 {f2(num(sq.get('price')))}，当日 {sign(s_chg)}，近20日 {sign(s_20d)}，近60日 {sign(s_60d)}，年初至今 {sign(s_ytd)}。"
         f"universe {len(U)} 只成分中有 {breadth_neg} 只处于 MA20 下方，"
         + ("说明回调已扩散至板块多数个股，属'普跌后的修复观察期'。" if breadth_neg > 18 else
            ("多数个股仍在 MA20 上方，趋势结构基本完好。" if breadth_neg < 10 else "涨跌分化明显，属结构性行情。"))),
        ("② 需求是真实的还是情绪/补库驱动？", nar["prosperity"][0][1] + f"（来源：{nar['prosperity'][0][2]}）"),
        ("③ 供给格局与定价权在谁手上？", nar["competition"]),
        ("④ 估值隐含了什么预期？",
         f"板块 PE(TTM) {f2(s_pe)}、PB {f2(s_pb)}（来源：腾讯自选股行情接口，{RUNDATE_H}）。"
         + ("估值处于高位，已price-in较多乐观预期，对业绩兑现的容错率低。" if (s_pe or 0) > 60 else
            ("估值处于中性偏低区间，安全边际相对充足。" if (s_pe or 0) < 25 else "估值处于中性区间。"))),
        ("⑤ 业绩兑现的时间点与证据？", nar["catalysts"][0][1] + f"（时点：{nar['catalysts'][0][0]}）。" +
         (nar["prosperity"][3][1] if len(nar["prosperity"]) > 3 else nar["prosperity"][-1][1])),
        ("⑥ 什么会让我错（证伪条件）？", nar["bear"][0] + " " + nar["bear"][1]),
        ("⑦ 现在该怎么做？",
         f"板块评级 <b>{rating}</b>（{rating_state}）" + (f"　{qb_note}" if qb_note else "") + "。"
         f"回抽确认候选 {len(cands)} 只，接近/支撑观察 {len(near)} 只，未到确认位 {len(deep)} 只，已站上MA20 {len(above)} 只。"
         f"操作以'确认触发价=收盘站上MA20、失效价=跌破近40日最低'为纪律。"),
    ]

    # ---------- HTML ----------
    def rowspan_chain():
        out = ""
        for seg, desc, players in nar["chain"]:
            out += (f'<tr><td class="tk">{E(seg)}</td><td>{E(desc)}</td>'
                    f'<td class="rz">{E(players)}</td></tr>')
        return out

    def prosperity_rows():
        out = ""
        for t, txt, src in nar["prosperity"]:
            out += (f'<div class="pros"><div class="pros-t">{E(t)}</div>'
                    f'<div class="pros-b">{E(txt)}</div>'
                    f'<div class="src">来源：{E(src)}</div></div>')
        return out

    def core_rows():
        out = ""
        for u in core:
            out += (f'<tr><td class="tk">{E(u["name"])}<span class="code">{u["code"]}</span></td>'
                    f'<td class="num">{f2(u["price"])}</td>'
                    f'<td class="num">{sign(u["chg"])}</td>'
                    f'<td class="num">{sign(u["chg20d"])}</td>'
                    f'<td class="num">{sign(u["chgYtd"])}</td>'
                    f'<td class="num">{f2(u["pe"]) if u["pe"] and u["pe"]>0 else "<span class=missing>亏损/NA</span>"}</td>'
                    f'<td class="num">{f2(u["pb"])}</td>'
                    f'<td class="num">{f2(u["mcap"])}</td>'
                    f'<td class="num">{sign(u["distMa20"])}</td></tr>')
        return out

    def vol_cell(u):
        vs, vg = u.get("volScore"), u.get("volGrade")
        if vs is None or vg is None:
            return '<td class="num"><span class=missing>[MISSING]</span></td>'
        cls = {"强": "up", "中": "flat", "弱": "down"}.get(vg, "flat")
        return (f'<td class="num {cls}">{vs}<span class="code">{E(vg)}'
                f'{" · " + E(u.get("volDetail")) if u.get("volDetail") else ""}</span></td>')

    def cand_rows(lst):
        if not lst:
            return '<tr><td colspan="11" class="missing">当前无符合该分级的标的</td></tr>'
        out = ""
        for u in lst:
            cf = u.get("_confirm") or "待确认"
            ccls = "up" if cf == "已确认" else "flat"
            out += (f'<tr><td class="tk">{E(u["name"])}<span class="code">{u["code"]}</span></td>'
                    f'<td class="num">{f2(u["price"])}</td>'
                    f'<td class="num">{f2(u["swingLow"])}<span class="code">{u.get("swingLowDate") or ""}</span></td>'
                    f'<td class="num">{sign(u["reboundPct"])}</td>'
                    f'<td class="num">{sign(u["distMa20"])}</td>'
                    f'<td class="num">{f2(u["rsi6"])}</td>'
                    f'<td class="num">{"是" if (u["ma5"] and u["ma10"] and u["ma5"]>u["ma10"]) else "否"}</td>'
                    + vol_cell(u) +
                    f'<td class="num trig">{f2(u["ma20"])}</td>'
                    f'<td class="num stop">{f2(u["swingLow"])}</td>'
                    f'<td class="num {ccls}">{cf}</td></tr>')
        return out

    def mup_rows(lst):
        """表4 · 主升浪买点区 专用（含「确认态」列）。已确认=扳机已扣动；待确认=setup 未确认。"""
        if not lst:
            return '<tr><td colspan="11" class="missing">当前无「主升浪买点区」候选</td></tr>'
        out = ""
        for u in lst:
            cf = u.get("_confirm") or "待确认"
            ccls = "up" if cf == "已确认" else "flat"
            out += (f'<tr><td class="tk">{E(u["name"])}<span class="code">{u["code"]}</span></td>'
                    f'<td class="num">{f2(u["price"])}</td>'
                    f'<td class="num">{f2(u["swingLow"])}<span class="code">{u.get("swingLowDate") or ""}</span></td>'
                    f'<td class="num">{sign(u["reboundPct"])}</td>'
                    f'<td class="num">{sign(u["distMa20"])}</td>'
                    f'<td class="num">{f2(u["rsi6"])}</td>'
                    f'<td class="num">{"是" if (u["ma5"] and u["ma10"] and u["ma5"]>u["ma10"]) else "否"}</td>'
                    + vol_cell(u) +
                    f'<td class="num trig">{f2(u["ma20"])}</td>'
                    f'<td class="num stop">{f2(u["swingLow"])}</td>'
                    f'<td class="num {ccls}">{cf}</td></tr>')
        return out

    bull_li = "".join(f"<li>{E(x)}</li>" for x in nar["bull"])
    bear_li = "".join(f"<li>{E(x)}</li>" for x in nar["bear"])
    risk_li = "".join(f"<li>{E(x)}</li>" for x in nar["risks"])
    cat_rows = "".join(
        f'<tr><td class="tk">{E(a)}</td><td>{E(b)}</td><td class="num">{E(c)}</td></tr>'
        for a, b, c in nar["catalysts"])
    pm7_html = "".join(f'<div class="q"><div class="q-t">{E(q)}</div><div class="q-a">{a}</div></div>'
                       for q, a in pm7)
    peer_rows = "".join(
        f'<tr><td class="tk">{E(p["name"])}<span class="code">{p["code"]}</span></td>'
        f'<td class="num">{sign(p["chg"])}</td><td class="num">{sign(p["chg20d"])}</td>'
        f'<td class="num">{sign(p["chg60d"])}</td><td class="num">{sign(p["chgYtd"])}</td>'
        f'<td class="num">{f2(p["pe"])}</td><td class="num">{f2(p["pb"])}</td></tr>' for p in peers)

    if lag_basis == "chg":
        lag_txt = " / ".join(f'{u["name"]}{u["chg"]:+.2f}%' for u in lag_top) \
            or "无（板块个股当日普遍收涨）"
    else:
        lag_txt = (" / ".join(f'{u["name"]}{u["distMa20"]:+.2f}%' for u in lag_top)
                   + "（距MA20）") if lag_top else "无（板块个股普遍在MA20上方）"

    action = f"""
    <table><thead><tr><th>分层</th><th>标的</th><th>行动</th><th>触发/条件</th></tr></thead><tbody>
    <tr><td class="tk">回抽确认候选</td><td>{E(' / '.join(u['name'] for u in cands[:6])) or '<span class=missing>无</span>'}</td>
        <td class="up">分批建仓（右侧）</td><td>收盘站上 MA20 且成交量放大，失效价为近40日最低</td></tr>
    <tr><td class="tk">接近/支撑观察</td><td>{E(' / '.join(u['name'] for u in near[:6])) or '<span class=missing>无</span>'}</td>
        <td class="flat">观察名单</td><td>等待回抽至 MA20 附近或 RSI_6 修复至 40 以上</td></tr>
    <tr><td class="tk">未到确认位</td><td>{E(' / '.join(u['name'] for u in deep[:6])) or '<span class=missing>无</span>'}</td>
        <td class="down">等待证据</td><td>距 MA20 深度为负、超卖，仅技术反抽，不视为回抽确认</td></tr>
    <tr><td class="tk">已站上 MA20</td><td>{E(' / '.join(u['name'] for u in above[:6])) or '<span class=missing>无</span>'}</td>
        <td class="flat">持有 / 不追高</td><td>正乖离过大者注意均值回归，回踩 MA20 不破可加</td></tr>
    </tbody></table>"""

    H = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{E(name)}板块深度分析 · {RUNDATE_H}</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;
background:#f4f5f7;color:#1a1d23;line-height:1.7;padding:0 0 60px}}
.wrap{{max-width:1180px;margin:0 auto;padding:0 20px}}
header{{background:linear-gradient(135deg,#1e3a5f 0%,#2d5a87 100%);color:#fff;padding:38px 0 30px;margin-bottom:26px}}
header .wrap{{display:flex;justify-content:space-between;align-items:flex-end;flex-wrap:wrap;gap:14px}}
h1{{font-size:27px;font-weight:700;letter-spacing:.5px}}
.sub{{opacity:.9;font-size:14px;margin-top:7px}}
.rating-box{{text-align:right}}
.rating{{font-size:22px;font-weight:700;padding:5px 16px;border-radius:6px;background:rgba(255,255,255,.16);display:inline-block}}
.rating.up{{color:#ff8a80}} .rating.down{{color:#a5d6a7}} .rating.flat{{color:#ffe082}}
section{{background:#fff;border-radius:10px;padding:26px 30px;margin-bottom:22px;box-shadow:0 1px 3px rgba(0,0,0,.07)}}
h2{{font-size:19px;color:#1e3a5f;padding-bottom:11px;margin-bottom:18px;border-bottom:2px solid #e8eaed;
display:flex;align-items:center;gap:10px}}
h2 .n{{background:#1e3a5f;color:#fff;width:27px;height:27px;border-radius:50%;display:inline-flex;
align-items:center;justify-content:center;font-size:14px;flex:0 0 auto}}
h3{{font-size:15px;color:#2d5a87;margin:20px 0 10px;font-weight:600}}
p{{margin-bottom:11px;font-size:14.5px}}
ul{{margin:0 0 12px 20px}} li{{margin-bottom:7px;font-size:14.5px}}
.lead{{background:#eef4fa;border-left:4px solid #2d5a87;padding:15px 18px;border-radius:0 6px 6px 0;
margin-bottom:18px;font-size:15px}}
table{{width:100%;border-collapse:collapse;font-size:13.5px;margin:12px 0}}
th{{background:#eef1f5;padding:10px 8px;text-align:left;font-weight:600;color:#33415c;
border-bottom:2px solid #d5dae1;white-space:nowrap;font-size:12.5px}}
td{{padding:9px 8px;border-bottom:1px solid #eef0f3;vertical-align:middle}}
tr:hover td{{background:#fafbfc}}
.num{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}
.tk{{font-weight:600;white-space:nowrap}}
.code{{display:block;font-size:11px;color:#8792a5;font-weight:400}}
.rz{{font-size:12.5px;color:#5a6478;line-height:1.55}}
.up{{color:#c62828;font-weight:600}} .down{{color:#2e7d32;font-weight:600}} .flat{{color:#666}}
.missing{{color:#b0b7c3;font-size:11.5px;font-style:italic}}
.trig{{color:#c62828;font-weight:600}} .stop{{color:#2e7d32;font-weight:600}}
.chart{{width:100%;height:400px;margin:14px 0}}
.chart-sm{{height:350px}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:22px}}
@media(max-width:860px){{.grid2{{grid-template-columns:1fr}}}}
.bull,.bear{{padding:16px 18px;border-radius:8px}}
.bull{{background:#fdf0ef;border:1px solid #f5c9c4}}
.bear{{background:#eef7ef;border:1px solid #c3e0c6}}
.bull h3{{color:#c62828;margin-top:0}} .bear h3{{color:#2e7d32;margin-top:0}}
.kpi{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin:16px 0}}
.kpi div{{background:#f7f9fb;border:1px solid #e6eaef;border-radius:8px;padding:12px 14px}}
.kpi .k{{font-size:12px;color:#7c8798}} .kpi .v{{font-size:19px;font-weight:700;margin-top:3px}}
.pros{{border-left:3px solid #7fa8cc;padding:10px 0 10px 14px;margin-bottom:14px}}
.pros-t{{font-weight:600;color:#1e3a5f;font-size:14.5px;margin-bottom:4px}}
.pros-b{{font-size:14px;margin-bottom:4px}}
.src{{font-size:11.5px;color:#8792a5}}
.q{{margin-bottom:14px;padding-bottom:12px;border-bottom:1px dashed #e3e7ec}}
.q:last-child{{border-bottom:none}}
.q-t{{font-weight:600;color:#1e3a5f;font-size:14.5px;margin-bottom:5px}}
.q-a{{font-size:14px;color:#33415c}}
.tag{{display:inline-block;padding:2px 9px;border-radius:11px;font-size:11.5px;font-weight:600;margin-left:6px}}
.tag.c{{background:#fdecea;color:#c62828}} .tag.n{{background:#fff8e1;color:#f57f17}}
.tag.d{{background:#eef7ef;color:#2e7d32}}
.note{{background:#fffbea;border:1px solid #f3e3a8;border-radius:8px;padding:13px 16px;font-size:13px;color:#6b5b1f;margin-top:14px}}
footer{{text-align:center;color:#8792a5;font-size:12.5px;padding:26px 20px 0;line-height:1.9}}
.disc{{font-weight:600;color:#c62828}}
</style></head>
<body>
<header><div class="wrap">
<div><h1>{E(name)}板块深度分析</h1>
<div class="sub">{E(nar['label'])}　·　数据时点 {RUNDATE_H}（收盘/盘中实时）　·　数据源：腾讯自选股行情接口</div></div>
<div class="rating-box"><div class="sub">板块评级（人工）</div><div class="rating {rcls}">{E(rating)}</div>
<div class="sub">{E(rating_state)}</div>
<div class="sub qb">{QB_EMOJI.get(qb_state, "")} {E(qb_note) if qb_note else "季度技术面：数据不足，暂以人工评级为准"}</div></div>
</div></header>

<div class="wrap">

<section>
<h2><span class="n">1</span>摘要与 PM 七问</h2>
<div class="lead"><b>一句话定位：</b>{E(nar['position'])}</div>
<div class="kpi">
<div><div class="k">板块当日</div><div class="v">{sign(s_chg)}</div></div>
<div><div class="k">近20日</div><div class="v">{sign(s_20d)}</div></div>
<div><div class="k">近60日</div><div class="v">{sign(s_60d)}</div></div>
<div><div class="k">年初至今</div><div class="v">{sign(s_ytd)}</div></div>
<div><div class="k">PE(TTM)</div><div class="v">{f2(s_pe)}</div></div>
<div><div class="k">PB</div><div class="v">{f2(s_pb)}</div></div>
</div>
<p><b>落后补涨候选（{"当日跌幅最深" if lag_basis == "chg" else "距MA20仍为负"}）：</b>{E(lag_txt)}</p>
{pm7_html}
</section>

<section>
<h2><span class="n">2</span>板块定义与产业链地图</h2>
<p>{E(name)}板块采用 <b>{E(nar['label'])}</b> 作为统计口径，成分股共 {len(U)} 只纳入本次深度跟踪
（按流通市值降序取前 40 只；若板块全部成分不足 40 只则全取，已剔除 ST/*ST 与北交所标的，保留科创板 688 标的）。</p>
<table><thead><tr><th>环节</th><th>覆盖内容</th><th>代表标的</th></tr></thead>
<tbody>{rowspan_chain()}</tbody></table>
<h3>同类子板块横向对比</h3>
<div id="chartSub" class="chart chart-sm"></div>
<table><thead><tr><th>子板块</th><th>当日</th><th>近20日</th><th>近60日</th><th>年初至今</th><th>PE(TTM)</th><th>PB</th></tr></thead>
<tbody>{peer_rows}</tbody></table>
</section>

<section>
<h2><span class="n">3</span>行业景气（价格周期 / TAM / 商业模式）</h2>
{prosperity_rows()}
<h3>板块指数年初至今走势</h3>
<div id="chartYtd" class="chart"></div>
<div class="note">走势数据为板块指数日K前复权收盘价，区间 {E(ytd_d[0]) if ytd_d else 'N/A'} ~ {E(ytd_d[-1]) if ytd_d else 'N/A'}，
共 {len(ytd_d)} 个交易日，来源：腾讯自选股 K线接口。纵轴为相对区间首日的累计涨跌幅（%）。</div>
</section>

<section>
<h2><span class="n">4</span>竞争格局与核心公司画像</h2>
<p>{E(nar['competition'])}</p>
<h3>核心公司实时行情与估值（按总市值降序前 12）</h3>
<table><thead><tr><th>标的</th><th>最新价</th><th>当日</th><th>近20日</th><th>年初至今</th>
<th>PE(TTM)</th><th>PB</th><th>总市值(亿元)</th><th>距MA20</th></tr></thead>
<tbody>{core_rows()}</tbody></table>
<div class="note">行情、估值与市值均取自腾讯自选股行情接口，时点 {RUNDATE_H}。PE 为负表示当期亏损，已标注为「亏损/NA」。</div>
</section>

<section>
<h2><span class="n">5</span>估值全景</h2>
<p>下图对核心公司的 PE(TTM) 与 PB 做双轴对比，用于识别「高PE但低PB」（资产重、盈利周期底部）
与「低PE但高PB」（盈利高点、资产轻）两类风险结构。板块整体 PE(TTM) {f2(s_pe)}、PB {f2(s_pb)}。</p>
<div id="chartVal" class="chart"></div>
</section>

<section>
<h2><span class="n">6</span>多空辩论</h2>
<div class="grid2">
<div class="bull"><h3>Bull · 多头逻辑</h3><ul>{bull_li}</ul></div>
<div class="bear"><h3>Bear · 空头逻辑</h3><ul>{bear_li}</ul></div>
</div>
</section>

<section>
<h2><span class="n">7</span>催化剂日历（未来 3~6 个月）</h2>
<table><thead><tr><th>时间窗口</th><th>事件</th><th>方向</th></tr></thead><tbody>{cat_rows}</tbody></table>
</section>

<section>
<h2><span class="n">8</span>个股回抽确认位跟踪</h2>
<p><b>方法：</b>在板块 universe 内，用「距 MA20 幅度 + RSI_6 修复程度 + 均线多头排列」三因子定位处于
<b>回抽确认窗口</b>的标的。<b>确认触发价 = 收盘价站上 MA20</b>；<b>失效价 = 跌破近 40 个交易日最低价</b>（swing low）。
分级标准：距MA20 在 0%~-10% 且 RSI_6 在 32~64 之间 → 回抽确认候选；-10%~-20% → 接近/支撑观察；
低于 -20% → 未到确认位（仅技术反抽）；距MA20 > 0 → 已站上 MA20。<br><b>量能评分（0-100）</b>＝缩量回踩(50分：近5日均量/20日均量，≤0.5 满分)＋放量确认(50分：当日量/近5日均量，≥1.2 满分)；<b>强 ≥75</b>（缩量回踩后已放量，最理想的回抽形态）/ <b>中 40~74</b> / <b>弱 &lt;40</b>（量能未配合，信号可靠性低）。量能数据取自日K成交量，时点同下表。</p>

<div class="lead"><b>今日「回抽确认」入选名单（口径与下表 1 完全一致：距MA20 0%~-10% ＋ RSI_6 32~64 ＋ 量能强/中，不要求 MA5&gt;MA10）：</b>{strict_txt}<br><span class="src">该名单即当日推送「回抽确认」内容，并同步至腾讯自选股「回调买入」分组；下表 1 为同一批候选的完整明细表，两者口径一致、可对照。</span></div>
<h3>表1 · 回抽确认候选 <span class="tag c">{len(cands)} 只</span></h3>
<table><thead><tr><th>标的</th><th>最新价</th><th>近40日最低(日期)</th><th>自低点反弹</th>
<th>距MA20</th><th>RSI_6</th><th>MA5&gt;MA10</th><th>量能评分</th><th>确认触发价(MA20)</th><th>失效价</th><th>确认态</th></tr></thead>
<tbody>{cand_rows(cands)}</tbody></table>

<h3>表2 · 接近/支撑观察 <span class="tag n">{len(near)} 只</span></h3>
<table><thead><tr><th>标的</th><th>最新价</th><th>近40日最低(日期)</th><th>自低点反弹</th>
<th>距MA20</th><th>RSI_6</th><th>MA5&gt;MA10</th><th>量能评分</th><th>确认触发价(MA20)</th><th>失效价</th><th>确认态</th></tr></thead>
<tbody>{cand_rows(near)}</tbody></table>

<h3>表3 · 未到确认位（超卖，仅技术反抽） <span class="tag d">{len(deep)} 只</span></h3>
<table><thead><tr><th>标的</th><th>最新价</th><th>近40日最低(日期)</th><th>自低点反弹</th>
<th>距MA20</th><th>RSI_6</th><th>MA5&gt;MA10</th><th>量能评分</th><th>确认触发价(MA20)</th><th>失效价</th><th>确认态</th></tr></thead>
<tbody>{cand_rows(deep)}</tbody></table>
<h3>表4 · 主升浪买点区 <span class="tag c">{len(mup)} 只</span></h3>
{('<table><thead><tr><th>标的</th><th>最新价</th><th>近40日最低(日期)</th><th>自低点反弹</th><th>距MA20</th><th>RSI_6</th><th>MA5&gt;MA10</th><th>量能评分</th><th>确认触发价(MA20)</th><th>失效价</th><th>确认态</th></tr></thead><tbody>'+mup_rows(mup)+'</tbody></table>') if mup else '<p class="missing">当前无「主升浪买点区」候选（需同时满足：中期多头 MA20&gt;MA60 且 MA20&gt;MA10、近20日涨幅≥10% 且近5日≥-3%、距MA20 -15%~+5%、量能强/中，且出现重启确认——MACD 红柱(dif&gt;dea)且当日阳线 或 放量比&gt;1.2 且当日阳线（非一根小阳线）。买点区仅含「结构在生长 + 近段未转跌 + 真实 thrust」的标的；若主升浪标的全在 MA20 上方 +5% 以外（过度追高）或动能未反转，则暂无贴近买点，属正常。</p>'}
<h3>全 universe 距 MA20 分布</h3>
<div id="chartDist" class="chart" style="height:660px"></div>
<div class="note">红色=回抽确认候选，浅红=位于 MA20 下方的其他标的，灰色=已站上 MA20。
0 轴即 MA20 确认线，向右穿越视为触发确认。技术指标取自腾讯自选股技术指标接口（MA/MACD/RSI），时点 {RUNDATE_H}。</div>
</section>

<section>
<h2><span class="n">9</span>结论与行动映射</h2>
<div class="lead"><b>板块评级：{E(rating)}</b>　—　{E(nar['rating_state'])}</div>
{action}
<div class="note"><b>加码触发：</b>板块20日涨幅由负转正 + 候选标的收盘站上 MA20 + 板块指数未跌破前低。
<b>减仓触发：</b>个股跌破失效价（近40日最低）/ 行业景气二阶导放缓 / 业绩指引下修。</div>
</section>

<section>
<h2><span class="n">10</span>风险提示</h2>
<ul>{risk_li}</ul>
<div class="note">数据完整性说明：本报告 universe 共 {len(U)} 只，行情与技术指标覆盖率
{len([u for u in U if u['distMa20'] is not None])}/{len(U)}，
近40日K线覆盖率 {len([u for u in U if u.get('swingLow')])}/{len(U)}。
未获取到的字段一律标注 [MISSING]，未做任何估算或填充。</div>
</section>

<footer>
{E(name)}板块深度分析 · 生成时间 {RUNDATE_H} · 数据源：腾讯自选股（行情/技术指标/K线/板块成分）＋ 公开研报与新闻（已在正文标注来源与时点）<br>
<span class="disc">本报告仅供研究参考，不构成个人投资建议。</span>
</footer>
</div>

<script>
var OPT={{textStyle:{{fontFamily:'-apple-system,BlinkMacSystemFont,PingFang SC,Microsoft YaHei,sans-serif'}}}};
// 1) YTD 走势
echarts.init(document.getElementById('chartYtd')).setOption(Object.assign({{}},OPT,{{
 tooltip:{{trigger:'axis',valueFormatter:v=>v==null?'-':v.toFixed(2)+'%'}},
 grid:{{left:58,right:26,top:26,bottom:52}},
 xAxis:{{type:'category',data:{json.dumps(ytd_d)},axisLabel:{{fontSize:11,color:'#7c8798'}},
   axisLine:{{lineStyle:{{color:'#d5dae1'}}}}}},
 yAxis:{{type:'value',name:'累计涨跌幅(%)',nameTextStyle:{{fontSize:11,color:'#7c8798'}},
   axisLabel:{{formatter:'{{value}}%',fontSize:11,color:'#7c8798'}},
   splitLine:{{lineStyle:{{color:'#eef0f3'}}}}}},
 series:[{{name:'{E(name)}',type:'line',data:{json.dumps(ytd_pct)},smooth:true,symbol:'none',
   lineStyle:{{width:2.2,color:'#c62828'}},
   areaStyle:{{color:new echarts.graphic.LinearGradient(0,0,0,1,[
     {{offset:0,color:'rgba(198,40,40,.22)'}},{{offset:1,color:'rgba(198,40,40,.01)'}}])}},
   markLine:{{silent:true,symbol:'none',data:[{{yAxis:0,lineStyle:{{color:'#90a4ae',type:'dashed'}},
     label:{{formatter:'年初基准',fontSize:10}}}}]}}}}]
}}));
// 2) 子板块对比
echarts.init(document.getElementById('chartSub')).setOption(Object.assign({{}},OPT,{{
 tooltip:{{trigger:'axis',axisPointer:{{type:'shadow'}},valueFormatter:v=>v==null?'-':v.toFixed(2)+'%'}},
 legend:{{data:['年初至今','近20日'],top:4,textStyle:{{fontSize:12}}}},
 grid:{{left:58,right:26,top:44,bottom:64}},
 xAxis:{{type:'category',data:{json.dumps(peer_names)},
   axisLabel:{{fontSize:11.5,color:'#5a6478',interval:0,rotate:{0 if len(peer_names)<=4 else 18}}},
   axisLine:{{lineStyle:{{color:'#d5dae1'}}}}}},
 yAxis:{{type:'value',axisLabel:{{formatter:'{{value}}%',fontSize:11,color:'#7c8798'}},
   splitLine:{{lineStyle:{{color:'#eef0f3'}}}}}},
 series:[
  {{name:'年初至今',type:'bar',data:{json.dumps(peer_ytd)},barMaxWidth:34,
    itemStyle:{{color:p=>p.value>=0?'#c62828':'#2e7d32'}},
    label:{{show:true,position:'top',fontSize:10.5,formatter:p=>p.value==null?'-':p.value.toFixed(1)+'%'}}}},
  {{name:'近20日',type:'bar',data:{json.dumps(peer_20d)},barMaxWidth:34,
    itemStyle:{{color:p=>p.value>=0?'#ef9a9a':'#a5d6a7'}},
    label:{{show:true,position:'top',fontSize:10.5,formatter:p=>p.value==null?'-':p.value.toFixed(1)+'%'}}}}]
}}));
// 3) 估值 PE vs PB 双轴
echarts.init(document.getElementById('chartVal')).setOption(Object.assign({{}},OPT,{{
 tooltip:{{trigger:'axis',axisPointer:{{type:'shadow'}}}},
 legend:{{data:['PE(TTM)','PB'],top:4,textStyle:{{fontSize:12}}}},
 grid:{{left:58,right:58,top:44,bottom:86}},
 xAxis:{{type:'category',data:{json.dumps(val_names)},
   axisLabel:{{fontSize:11,color:'#5a6478',interval:0,rotate:34}},
   axisLine:{{lineStyle:{{color:'#d5dae1'}}}}}},
 yAxis:[
  {{type:'value',name:'PE(TTM)',nameTextStyle:{{fontSize:11,color:'#7c8798'}},
    axisLabel:{{fontSize:11,color:'#7c8798'}},splitLine:{{lineStyle:{{color:'#eef0f3'}}}}}},
  {{type:'value',name:'PB',nameTextStyle:{{fontSize:11,color:'#7c8798'}},
    axisLabel:{{fontSize:11,color:'#7c8798'}},splitLine:{{show:false}}}}],
 series:[
  {{name:'PE(TTM)',type:'bar',data:{json.dumps(val_pe)},barMaxWidth:30,itemStyle:{{color:'#2d5a87'}}}},
  {{name:'PB',type:'line',yAxisIndex:1,data:{json.dumps(val_pb)},smooth:true,
    lineStyle:{{width:2.2,color:'#ef6c00'}},itemStyle:{{color:'#ef6c00'}},symbolSize:7}}]
}}));
// 4) 距 MA20 分布
echarts.init(document.getElementById('chartDist')).setOption(Object.assign({{}},OPT,{{
 tooltip:{{trigger:'axis',axisPointer:{{type:'shadow'}},valueFormatter:v=>v==null?'-':v.toFixed(2)+'%'}},
 grid:{{left:92,right:60,top:20,bottom:44}},
 xAxis:{{type:'value',name:'距MA20(%)',nameTextStyle:{{fontSize:11,color:'#7c8798'}},
   axisLabel:{{formatter:'{{value}}%',fontSize:11,color:'#7c8798'}},
   splitLine:{{lineStyle:{{color:'#eef0f3'}}}}}},
 yAxis:{{type:'category',data:{json.dumps(dist_names)},
   axisLabel:{{fontSize:11.5,color:'#5a6478'}},axisLine:{{lineStyle:{{color:'#d5dae1'}}}}}},
 series:[{{type:'bar',data:{json.dumps([{"value": v, "itemStyle": {"color": c}} for v, c in zip(dist_vals, dist_colors)])},
   barMaxWidth:15,
   label:{{show:true,position:'right',fontSize:10.5,color:'#5a6478',
     formatter:p=>p.value==null?'-':p.value.toFixed(1)+'%'}},
   markLine:{{silent:true,symbol:'none',data:[{{xAxis:0,lineStyle:{{color:'#c62828',type:'dashed',width:1.6}},
     label:{{formatter:'MA20 确认线',fontSize:10.5,color:'#c62828'}}}}]}}}}]
}}));
</script>
</body></html>"""

    path = f"{BASE}/{name}板块深度分析_{RUNDATE}.html"
    open(path, "w", encoding="utf-8").write(H)

    # ---------- _summary.json 的 cands（严格口径，供推送 / 自选股同步） ----------
    cand_out = [{"name": u["name"], "code": u["code"],
                 "distMa20": round(u["distMa20"], 2) if u["distMa20"] is not None else None,
                 "volScore": u.get("volScore"), "volGrade": u.get("volGrade"),
                 "volDetail": u.get("volDetail"),
                 "rsi6": round(u["rsi6"], 1) if u.get("rsi6") is not None else None,
                 "confirm": u.get("_confirm")}
                for u in strict]

    # ---------- _summary.json 的 mups（表4 · 主升浪买点区，供推送汇总） ----------
    # 口径：中期多头(MA20>MA60 且 MA20>MA10) + 近20日≥10% 且近5日≥-3% + 回踩区-15%~+5% + 量能强/中 + 重启确认(MACD红柱+阳线 或 放量比>1.2+阳线)。
    # Step G 写自选股直接采用本口径（不再额外收窄到 -15%~0%），与报告表4一致。
    mup_out = [{"name": u["name"], "code": u["code"],
                "price": round(u["price"], 2) if u.get("price") is not None else None,
                "distMa20": round(u["distMa20"], 2) if u["distMa20"] is not None else None,
                "rsi6": round(u["rsi6"], 1) if u.get("rsi6") is not None else None,
                "volScore": u.get("volScore"), "volGrade": u.get("volGrade"),
                "volDetail": u.get("volDetail"),
                "confirm": u.get("_confirm"),
                "chg20d": round(u["chg20d"], 2) if u.get("chg20d") is not None else None}
               for u in mup]

    return dict(name=name, path=path, rating=rating, position=nar["position"],
                lag=lag_txt, cands=cand_out, mups=mup_out, s_ytd=s_ytd, s_20d=s_20d, s_pe=s_pe,
                bull=nar["bull"][0], bear=nar["bear"][0],
                rating_qb=rating_qb, qb_note=qb_note, qb_state=qb_state)


if __name__ == "__main__":
    out = []
    for nm in (sys.argv[1:] or NAMES):
        r = build(nm)
        out.append(r)
        print(f"OK {nm}: 评级={r['rating']} 候选{len(r['cands'])}只 -> {os.path.basename(r['path'])}")
    json.dump(out, open(f"{DATA}/_summary.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
