#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""四层技术面体检（动能/结构/量能/位置）+ 评级裁决结论。

用途：为飞书推送日报的每个板块生成「技术分析」块，把笼统的「技术面偏弱」
拆解为 4 个可判定层级，并按「评级 vs 技术面」裁决方法论输出一句话结论。

方法论（2026-08-18 固化，算力实证）：
  评级回答「买什么/方向对不对」，技术面回答「什么时候买/买哪一档」。
  两者分歧时只有 3 种情形需推翻评级：① 产业逻辑证伪 ② 中期趋势破位
  ③ 仅结构/量能/位置弱 → 保留评级方向、下调执行强度。
  典型格局：动能强 + 结构弱 + 量能未确认 = 缩量反弹修复，非主升浪起点。

颜色语义（与推送一致）：🔴 偏强/进攻 · 🟡 中性 · 🟢 偏弱/谨慎（含追高风险）。

字段硬约束（踩坑记录）：universe 当前价字段是 `price` 不是 `close`；
判断是否站上均线一律用预算好的 `distMa20/distMa60/distMa120`（正=上方），
不要自己拿价格比均线（误用 close 会得到 0/40 这类假读数）。

支持 A 股（有 sector_quote.volume_ratio / 个股 volRatio）与港股（仅 volDetail
放量比）两种数据形态，量能层指标自动降级并如实标注口径。
"""
import json
import os
import re
import statistics

__all__ = ["compute", "render_lines", "load_universe",
           "sector_bull_ratio", "main_uptrend_confirm", "pullback_confirm"]

# ---------- 工具 ----------


def _num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return None
    return None


def _vals(U, key):
    out = []
    for x in U:
        v = _num(x.get(key))
        if v is not None:
            out.append(v)
    return out


def _med(xs):
    return round(statistics.median(xs), 2) if xs else None


def _pct(cnt, n):
    return round(cnt / n * 100) if n else 0


def _pct_txt(p, lo=40):
    """低于阈值时加「仅」字强调，便于一眼看出弱项。"""
    return f"仅 {p}%" if p < lo else f"{p}%"


def _amp_ratio(vd):
    """从 volDetail「缩量比0.94/放量比1.37」解析放量比。"""
    if not isinstance(vd, str):
        return None
    m = re.search(r"放量比([\d.]+)", vd)
    return float(m.group(1)) if m else None


# ---------- 四层判定 ----------


def _momentum(U, n):
    a20 = sum(1 for x in U if (_num(x.get("distMa20")) or -1) > 0)
    md = sum(1 for x in U if (_num(x.get("macd")) or -1) > 0)
    m20 = _med(_vals(U, "chg20d"))
    p20, pmd = _pct(a20, n), _pct(md, n)
    m20s = f"{m20:+.1f}%" if m20 is not None else "n/a"
    metrics = f"站上MA20 {_pct_txt(p20)} · MACD红 {_pct_txt(pmd)} · 20日中位 {m20s}"
    if p20 >= 65 and pmd >= 60 and (m20 or 0) > 0:
        v, e = "强", "🔴"
    elif p20 <= 35 or (m20 is not None and m20 <= -5):
        v, e = "弱", "🟢"
    else:
        v, e = "中性", "🟡"
    return {"name": "动能层 · 短期", "metrics": metrics, "verdict": v, "emo": e,
            "raw": {"above20": p20, "macd": pmd, "chg20d_med": m20}}


def _structure(U, n):
    bull = sum(1 for x in U
               if (_num(x.get("ma20")) or 0) > (_num(x.get("ma60")) or 0) > 0)
    a120 = sum(1 for x in U if (_num(x.get("distMa120")) or -1) > 0)
    below60 = sum(1 for x in U if (_num(x.get("distMa60")) or -1) < 0)
    pb, pa, pb60 = _pct(bull, n), _pct(a120, n), _pct(below60, n)
    metrics = f"MA20>MA60 {_pct_txt(pb)} · 站上MA120 {_pct_txt(pa)}"
    if any("qbUptrend" in x for x in U):
        qb = sum(1 for x in U if x.get("qbUptrend") is True)
        metrics += f" · 季线多头 {_pct_txt(_pct(qb, n))}"
    if pb >= 60 and pa >= 60:
        v, e = "偏强", "🔴"
    elif pb < 40 or pa < 40:
        v, e = "偏弱", "🟢"
    else:
        v, e = "中性", "🟡"
    return {"name": "结构层 · 中期", "metrics": metrics, "verdict": v, "emo": e,
            "raw": {"bull": pb, "above120": pa, "below60_pct": pb60}}


def _volume(U, n, sq):
    g = {"强": 0, "中": 0, "弱": 0}
    for x in U:
        gr = x.get("volGrade")
        if gr in g:
            g[gr] += 1
    dist = f"量能 {g['强']}强/{g['中']}中/{g['弱']}弱"
    # 量比口径：板块量比（A股 sector_quote）> 个股量比中位 > 放量比中位（港股）
    ratio, label = None, None
    sr = _num((sq or {}).get("volume_ratio") or (sq or {}).get("volRatio"))
    if sr:
        ratio, label = sr, "板块量比"
    else:
        vrs = _vals(U, "volRatio")
        if vrs:
            ratio, label = _med(vrs), "个股量比中位"
        else:
            amps = [a for a in (_amp_ratio(x.get("volDetail")) for x in U) if a]
            if amps:
                ratio, label = _med(amps), "放量比中位"
    metrics = dist + (f" · {label} {ratio:.2f}" if ratio else "")
    ps = _pct(g["强"], n)
    if ps >= 20 or (ratio or 0) >= 1.30:
        v, e = "已确认", "🔴"
    elif g["强"] == 0 and (ratio or 1) < 0.85:
        v, e = "缩量", "🟢"
    else:
        v, e = "未确认", "🟡"
    return {"name": "量能层 · 确认", "metrics": metrics, "verdict": v, "emo": e,
            "raw": {"strong_pct": ps, "ratio": ratio, "dist": g}}


def _position(U, n):
    dm = _med(_vals(U, "distMa20"))
    dms = f"{dm:+.1f}%" if dm is not None else "n/a"
    lead = sorted([x for x in U if _num(x.get("chg20d")) is not None],
                  key=lambda y: -_num(y["chg20d"]))[:3]
    rs = [_num(x.get("rsi6")) for x in lead if _num(x.get("rsi6")) is not None]
    metrics = f"距MA20中位 {dms}"
    hi = max(rs) if rs else None
    if rs:
        lo = min(rs)
        tag = "（超买）" if hi and hi > 75 else ""
        metrics += f" · 龙头RSI6 {lo:.0f}~{hi:.0f}{tag}"
    if (dm is not None and dm > 5) or (hi is not None and hi > 75):
        v, e = "追高风险", "🟢"
    elif dm is not None and -8 <= dm <= 2 and (hi is None or hi <= 70):
        v, e = "低吸区", "🔴"
    else:
        v, e = "中性", "🟡"
    return {"name": "位置层 · 风险", "metrics": metrics, "verdict": v, "emo": e,
            "raw": {"distMa20_med": dm, "lead_rsi_hi": hi}}


# ---------- 主升浪确认态（2026-08-27 新增）----------

def sector_bull_ratio(U):
    """板块中期结构占比：MA20>MA60 的成分占比（0~1），用于「板块结构确立」判定。"""
    n = len(U)
    if n == 0:
        return 0.0
    bull = sum(1 for x in U
               if (_num(x.get("ma20")) or 0) > (_num(x.get("ma60")) or 0) > 0)
    return round(bull / n, 3)


def main_uptrend_confirm(u, bull_ratio):
    """主升浪买点区「确认态」标记（2026-09-02 收紧：去掉板块占比兜底）。

    仅个股自身扳机，不再以「板块 MA20>MA60 占比≥50%」单独兜底（避免板块强而
    个股弱被误判已确认）：
      - 已确认：个股已站上 MA20 且 MA20 仍上行(ma20>ma10) → 回踩后结构延续；
                或 放量比>1.5 且 当日阳线 → 强量能 thrust；
                或 MACD 红柱(dif>dea) → 动能金叉。
      - 待确认：仅结构到位、扳机未响（仍回踩中 / 个股未确认），高假突破风险。

    口径对齐框架：评级定方向、技术面定节奏、**量能扣扳机**；个股自身确认优先于板块。
    """
    vr = _num(u.get("volRatio"))
    dm = _num(u.get("distMa20"))
    chg = _num(u.get("chg"))
    ma20 = _num(u.get("ma20"))
    ma10 = _num(u.get("ma10"))
    dif = _num(u.get("dif"))
    dea = _num(u.get("dea"))
    rising = (ma20 is not None and ma10 is not None and ma20 > ma10)
    thrust = (vr is not None and vr > 1.5 and chg is not None and chg > 0)
    macd_red = (dif is not None and dea is not None and dif > dea)
    indiv = ((dm is not None and dm > 0 and rising) or thrust or macd_red)
    return "已确认" if indiv else "待确认"


def pullback_confirm(u, bull_ratio=None):
    """回抽确认候选「确认态」标记（2026-09-02 收紧：剔除弱反抽假信号）。

    板块 MA20>MA60 占比（bull_ratio）仅作**参考项**，不参与判定。
    个股确认态**只由条件2/条件3 决定**（满足任一条即「已确认」）。

    根因（2026-09-02）：原口径把"下行趋势边缘红柱 + 当日仍跌/平 + 缩量"也判「已确认」，
    导致"判断出回抽确认但实际没涨"。实测 09-02 的 12 只「已确认」全部仍在 MA20 下方，
    其中多只是 下跌/平盘 + 量比<1.0 + 仅 MACD 略红 的假信号。

    收紧后（与 main_uptrend_confirm 同级的"真实 thrust"标准）：
      条件2：放量阳线 thrust —— 当日涨幅≥+0.5% 且 量比 volRatio>1.2
             （剔除 +0.1% 毛刺阳线 与 量比1.1 边缘，要求真实资金回流）
      条件3：动能金叉 + 不跌 + 量能不缩 —— MACD 红柱(dif>dea) 且 当日不跌(chg≥0) 且 量比≥1.1
             （剔除下行趋势边缘红柱 / 缩量假信号，原 chg≥-1.0 把 -0.8% 下跌日也判确认）
    否则「待确认」（仍在缩量阴跌 / 单日弱反抽、动能未真转强，回抽尚未确认）。
    """
    chg = _num(u.get("chg"))
    vr = _num(u.get("volRatio"))
    dif = _num(u.get("dif"))
    dea = _num(u.get("dea"))
    # 条件2：放量阳线 thrust（真实资金回流，非毛刺）
    if (chg is not None and chg >= 0.5) and (vr is not None and vr > 1.2):
        return "已确认"
    # 条件3：动能金叉 + 当日不跌 + 量能不缩（剔除下行边缘红柱/缩量假信号）
    if (dif is not None and dea is not None and dif > dea) and (chg is not None and chg >= 0) and (vr is not None and vr >= 1.1):
        return "已确认"
    return "待确认"


# ---------- 裁决结论 ----------


def _verdict(rating, mo, st, vo, po):
    """评级×技术面 三态决策树（2026-08-18 用户拍板固化）。

    四组评级 × 各自的裁决问题：
      加码/加仓(进攻)=买不买、买哪档 · 持有(中性偏多)=拿不拿、减不减 ·
      观察(防守观望)=升不升、避不避 · 清仓/减仓(防守离场)=卖不卖、何时卖。
    铁律：评级定方向、技术面定节奏、量能扣扳机；技术面只调执行不改评级，
          唯一例外是破位（安全阀：技术面胜出、评级滞后）。
    清仓/减仓组 emoji 一律行动色 🟢（即使技术反弹，避免诱导反手）。
    短标签一律两段式「组·格局」：加码·双强共振 / 持有·等回踩 / 观察·可上调 / 清仓·反弹卖。
    """
    r = rating or "评级"
    mv, sv, vv = mo["verdict"], st["verdict"], vo["verdict"]
    strong_mo = mv == "强"
    weak_mo = mv == "弱"
    weak_st = sv == "偏弱"
    strong_st = sv == "偏强"
    confirmed = vv == "已确认"
    chase = po["verdict"] == "追高风险"
    below60 = st["raw"].get("below60_pct", 0)
    macd_pct = mo["raw"].get("macd", 100)
    # 破位：多数成分跌破MA60 且 MACD 翻绿 → 评级滞后、技术面胜出（安全阀）
    broken = below60 >= 65 and macd_pct < 45

    g = ("加码" if r in ("加码", "加仓") else
         "持有" if r == "持有" else
         "清仓" if r in ("减仓", "清仓", "放弃", "对冲") else "观察")
    P = f"{g}・"  # 两段式短标签前缀（分隔符用日文中点 ・，与推送四层分隔符统一）

    # 清仓/减仓：技术面不改变离场决策，只定卖点；emoji 一律行动色 🟢
    if g == "清仓":
        if strong_mo:
            return (f"「{r}」下反弹是最好的减仓/清仓窗口，不在反弹中反手加回"
                    f"（卖在人声鼎沸处）", "🟢", P + "反弹卖")
        if broken:
            return (f"「{r}」与技术面共振破位，坚决清仓离场、不抄底，等结构修复",
                    "🟢", P + "破位预警")
        return (f"「{r}」继续执行减仓/清仓，等企稳再评估", "🟢", P + "顺势走")

    # 观察：裁决问题 = 要不要上调介入
    if g == "观察":
        if broken:
            return (f"技术面与「{r}」共振破位，坚决回避，等结构修复", "🟢", P + "破位预警")
        if strong_mo and strong_st and confirmed:
            return (f"技术全面转强、评级偏保守，可上调至持有/试仓"
                    f"（基本面仍谨慎则仅按反弹对待）", "🔴", P + "可上调")
        if strong_mo:
            return (f"短期动能虽强，但"
                    f"{'结构未立' if weak_st else ''}"
                    f"{'、' if weak_st and not confirmed else ''}"
                    f"{'量能未确认' if not confirmed else ''}"
                    f"，维持「{r}」不追高", "🟡", P + "等确认")
        if weak_mo or weak_st:
            return (f"技术面与「{r}」一致偏弱，继续回避，等MA20收回", "🟢", P + "回避")
        return (f"技术面与「{r}」基本匹配，维持观望，等量能与中期结构双确认",
                "🟡", P + "匹配执行")

    # 持有：裁决问题 = 拿不拿、减不减
    if g == "持有":
        if broken:
            return (f"「{r}」评级下技术已破位，技术面胜出；先减仓兑现、保护利润，"
                    f"等结构修复再评估", "🟢", P + "破位预警")
        if strong_mo and strong_st and confirmed:
            return (f"「{r}」有效且技术已强于评级（动能/结构/量能三确认），"
                    f"可考虑上调至加码/加仓（若基本面同步确认）", "🔴", P + "双强共振")
        if strong_mo and weak_st and not confirmed:
            return (f"「{r}」有效，回踩是加仓点，仓位落紧贴MA20低位", "🟡", P + "等回踩")
        if strong_mo and weak_st and confirmed:
            return (f"「{r}」短期动能与量能确认、中期未立，可参与反弹但止盈纪律从严",
                    "🟡", P + "反弹可参与")
        if weak_mo and weak_st:
            return (f"动能结构双弱，部分兑现、设好止盈，等MA20收回", "🟢", P + "双弱背离")
        if weak_mo and strong_st:
            return (f"中期结构完好、短期回撤，继续持有，回抽确认位是加仓点",
                    "🔴", P + "健康回踩")
        return (f"「{r}」方向与技术面基本匹配，按评级执行，等量能扳机放大仓位"
                f"{'，避免追已超买龙头' if chase else ''}", "🟡", P + "匹配执行")

    # 加码/加仓：裁决问题 = 买不买、买哪档（A-F）
    if broken:
        return (f"「{r}」仍挂但技术已破位（多数成分跌破MA60、MACD翻绿），"
                f"技术面胜出、评级滞后；降级看待、回避，等结构修复", "🟢", P + "破位预警")
    if strong_mo and strong_st and confirmed:
        return (f"「{r}」与技术面共振，动能/结构/量能三重确认，可按评级正常执行；"
                f"但已走强、回踩更优，不追高", "🔴", P + "双强共振")
    if strong_mo and weak_st and not confirmed:
        # 健康等回踩：方向成立、等回踩买点 → 2026-08-18 用户拍板上调为 🔴（偏强/进攻，
        # 联动 Step G：裁决 emoji==🔴 的板块进自选股，健康等回踩板块随之纳入）
        return (f"「{r}」方向成立（评级定方向），技术面定节奏=中期未立、等回踩；"
                f"量能未确认=扳机未响，仓位落紧贴 MA20 的低位标的", "🔴", P + "健康等回踩")
    if strong_mo and weak_st and confirmed:
        return (f"「{r}」短期动能与量能确认、中期结构未立，可参与反弹但止盈纪律从严",
                "🟡", P + "反弹可参与")
    if strong_st and mv == "中性" and not confirmed:
        return (f"「{r}」中期结构已立、短期动能未共振、量能未确认"
                f"{'，龙头超买不追高' if chase else ''}"
                f"，等回踩至 MA20 附近再放大仓位", "🟡", P + "结构已立")
    if weak_mo and weak_st:
        return (f"技术面与「{r}」背离，动能与结构双弱，建议下调执行强度、等 MA20 收回",
                "🟢", P + "双弱背离")
    if weak_mo and strong_st:
        return (f"「{r}」中期结构完好、短期回撤，属健康回踩，回抽确认位是主要机会",
                "🔴", P + "健康回踩")
    return (f"「{r}」方向与技术面基本匹配，按评级执行，等量能扳机放大仓位"
            f"{'，避免追已超买龙头' if chase else ''}", "🟡", P + "匹配执行")


# ---------- 对外接口 ----------


def load_universe(data_dir, sector_name):
    p = os.path.join(data_dir, f"{sector_name}.json")
    if not os.path.exists(p):
        return None, None
    with open(p, encoding="utf-8") as f:
        d = json.load(f)
    return d.get("universe") or [], d.get("sector_quote") or {}


def compute(universe, sector_quote=None, rating=None):
    """返回 {n, layers[4], conclusion, conclusion_emo}；数据缺失返回 None。"""
    U = [x for x in (universe or []) if isinstance(x, dict)]
    n = len(U)
    if n == 0:
        return None
    mo, st = _momentum(U, n), _structure(U, n)
    vo, po = _volume(U, n, sector_quote), _position(U, n)
    txt, emo, vtype = _verdict(rating, mo, st, vo, po)
    return {"n": n, "layers": [mo, st, vo, po],
            "conclusion": txt, "conclusion_emo": emo, "verdict_type": vtype}


def render_lines(t4, pad="　　", pad2="　　　　"):
    """渲染为飞书 markdown 行列表（严禁 HTML 标签，缩进用全角空格）。"""
    if not t4:
        return [f"{pad}技术分析：[MISSING] 成分技术面数据缺失"]
    out = [f"{pad}**技术分析（{t4['n']} 只成分）：**"]
    for L in t4["layers"]:
        name = L["name"].replace(" · ", "・")
        metrics = L["metrics"].replace(" · ", "・")
        out.append(f"{pad2}{name}　{metrics}　{L['emo']}{L['verdict']}")
    out.append(f"{pad}**结论：{t4['conclusion_emo']}【{t4['verdict_type']}】{t4['conclusion']}**")
    return out


if __name__ == "__main__":
    import sys
    ws = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    name = sys.argv[1] if len(sys.argv) > 1 else "港股半导体"
    rating = sys.argv[2] if len(sys.argv) > 2 else None
    U, sq = load_universe(os.path.join(ws, "data"), name)
    print("\n".join(render_lines(compute(U, sq, rating))))
