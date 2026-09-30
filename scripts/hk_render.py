#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""港股板块深度分析 HTML 渲染器（10 节 + 4 图，港元计价，失效价=近 40 日 swing low）。

跨市场适配（对齐 a-share-sector-pullback skill 的港股条款）：
  ① 计价一律 HK$，禁用人民币符号；
  ② 失效价 = 近 40 日 K 线最低价（swing low），非 A 股的固定历史底；
  ③ 确认触发价 = MA20；④ 距 MA20% 口径与 A 股一致。

2026-08-10 重构：个股状态/候选名单/行动价位**全部由数据动态计算**，
narratives 只提供定性叙事，杜绝次日调度沿用陈旧个股结论。
"""
import json
import os
import statistics
import sys
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
RUNDATE = os.environ.get("RUNDATE") or datetime.now().strftime("%Y%m%d")
RUNDATE_DASH = f"{RUNDATE[:4]}-{RUNDATE[4:6]}-{RUNDATE[6:]}"

CSS = """
  :root{--bg:#f5f6f8;--card:#fff;--ink:#1f2329;--sub:#646a73;--line:#e5e6eb;--blue:#185fa5;--red:#a32d2d;--green:#3b6d11;--amber:#854f0b;}
  *{box-sizing:border-box;margin:0;padding:0;}
  body{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;background:var(--bg);color:var(--ink);line-height:1.7;padding:32px 20px;}
  .wrap{max-width:1080px;margin:0 auto;}
  header{border-left:4px solid var(--blue);padding:8px 16px;margin-bottom:24px;}
  header h1{font-size:22px;font-weight:600;}
  header .meta{color:var(--sub);font-size:13px;margin-top:6px;}
  .card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:20px 22px;margin-bottom:18px;}
  .card h2{font-size:17px;font-weight:600;margin-bottom:12px;color:var(--blue);}
  .card h3{font-size:14px;font-weight:600;margin:14px 0 6px;}
  p,li{font-size:14px;color:var(--ink);}
  ul,ol{padding-left:20px;}
  li{margin-bottom:6px;}
  .tag{display:inline-block;background:#e6f1fb;color:var(--blue);border-radius:6px;padding:2px 10px;font-size:12px;margin:2px 4px 2px 0;}
  .up{color:var(--red);} .down{color:var(--green);}
  table{width:100%;border-collapse:collapse;margin-top:10px;font-size:13px;}
  th,td{border:1px solid var(--line);padding:7px 9px;text-align:center;}
  th{background:#f2f3f5;font-weight:600;}
  .kpi{display:flex;flex-wrap:wrap;gap:14px;margin:10px 0;}
  .kpi div{flex:1;min-width:150px;background:#fafbfc;border:1px solid var(--line);border-radius:8px;padding:12px;}
  .kpi b{font-size:18px;color:var(--blue);}
  .kpi .sub{font-size:12px;color:var(--sub);}
  .chart{width:100%;height:380px;margin-top:8px;}
  .bull{color:var(--red);} .bear{color:var(--green);}
  .rating-box{background:#fff8e6;border:1px solid #f0d9a0;border-radius:8px;padding:12px 14px;margin:10px 0;font-size:14px;}
  .note{font-size:12px;color:var(--sub);margin-top:8px;}
  .disc{font-size:12px;color:var(--sub);border-top:1px dashed var(--line);margin-top:20px;padding-top:12px;}
"""


def pct(v, digits=2):
    return "[MISSING]" if v is None else f"{v:+.{digits}f}%"


def cls(v):
    return "" if v is None else ("up" if v >= 0 else "down")


def fmt(v, digits=2):
    if v is None or v == 0:
        return "[MISSING]" if v is None else "0"
    return f"{v:.{digits}f}".rstrip("0").rstrip(".")


# ---------- 动态分层：回抽确认判定 ----------
def classify(r):
    """返回 (tier, 状态文案)。tier ∈ cand/near/window/support/avoid/above/hot/none"""
    d, rsi, up = r.get("dist_ma20_pct"), r.get("rsi6"), r.get("ma5_gt_ma10")
    if d is None or rsi is None:
        return "none", "无技术信号（均线未成型）"
    if d >= 0:
        if rsi >= 70:
            return "hot", f"已站上MA20·超买不追(RSI {rsi:.0f})"
        return "above", "已站上MA20"
    if d < -20 or rsi < 32:
        return "avoid", f"超卖反抽·非回抽确认(RSI {rsi:.0f})"
    if d < -10:
        return "support", "接近/支撑企稳·观察"
    if -1 < d < 0:
        return "near", "贴近MA20·待确认"
    # -10 <= d <= -1
    if 40 <= rsi <= 58 and up:
        return "cand", "回抽确认候选"
    reason = "MA5<MA10" if not up else ("RSI偏低" if rsi < 40 else "RSI偏高")
    return "window", f"窗口内·条件未满足({reason})"


def build(sector, cfg):
    path_json = os.path.join(DATA, f"港股{sector}.json")
    with open(path_json, encoding="utf-8") as f:
        rows = json.load(f)

    for r in rows:
        r["tier"], r["status"] = classify(r)

    dists = [r["dist_ma20_pct"] for r in rows if r.get("dist_ma20_pct") is not None]
    med = statistics.median(dists)
    below = sum(1 for d in dists if d < 0)
    above_n = len(dists) - below
    avg20 = statistics.mean([r["chg_20d"] for r in rows if r.get("chg_20d") is not None])
    avg5 = statistics.mean([r["chg_5d"] for r in rows if r.get("chg_5d") is not None])
    avgtd = statistics.mean([r["change_percent"] for r in rows if r.get("change_percent") is not None])

    illiquid = set(cfg.get("illiquid", []))
    cands = [r for r in rows if r["tier"] == "cand"]
    watch = [r for r in rows if r["tier"] in ("near", "window", "support")]
    hots = [r for r in rows if r["tier"] == "hot"]
    avoids = [r for r in rows if r["tier"] == "avoid"]
    candset = {r["name"] for r in cands}

    # ---------- 落后补涨（当日涨跌幅最弱 3 只；全 0 则降级距MA20） ----------
    chg_rows = [r for r in rows if r.get("change_percent") is not None]
    use_chg = any(abs(r["change_percent"]) > 1e-9 for r in chg_rows)
    if use_chg:
        lag_src = sorted(chg_rows, key=lambda x: x["change_percent"])[:3]
        lag_txt = " / ".join(f"{r['name']}{r['change_percent']:+.2f}%" for r in lag_src)
        lag_label = "当日跌幅最深 / 涨幅最弱"
    else:
        lag_src = sorted([r for r in rows if r.get("dist_ma20_pct") is not None],
                         key=lambda x: x["dist_ma20_pct"])[:3]
        lag_txt = " / ".join(f"{r['name']}{r['dist_ma20_pct']:+.2f}%（距MA20）" for r in lag_src)
        lag_label = "距MA20 仍为负（盘前降级口径）"

    # ---------- 表：核心公司画像 ----------
    core_rows = ""
    for r in rows:
        if r["name"] not in cfg["core"]:
            continue
        pe = r.get("pe_ratio")
        pe_s = "N/M(亏损)" if (pe is None or pe < 0) else f"{pe:.1f}"
        core_rows += (
            f'<tr><td>{r["name"]}</td><td>{r["code"]}</td><td>{fmt(r.get("price"))}</td>'
            f'<td class="{cls(r.get("change_percent"))}">{pct(r.get("change_percent"))}</td>'
            f'<td class="{cls(r.get("chg_20d"))}">{pct(r.get("chg_20d"))}</td>'
            f'<td class="{cls(r.get("chg_ytd"))}">{pct(r.get("chg_ytd"))}</td>'
            f'<td>{pe_s}</td>'
            f'<td class="{cls(r.get("dist_ma20_pct"))}">{pct(r.get("dist_ma20_pct"))}</td>'
            f'<td>{r["status"]}</td></tr>\n'
        )

    # ---------- 回抽跟踪表 ----------
    def track_row(r):
        sl = r.get("swing_low_40")
        sl_s = "[MISSING]" if (sl is None or sl == 0) else fmt(sl, 3)
        mark = " ⚠低流动" if r["name"] in illiquid else ""
        vr = r.get("vol_ratio_20")
        return (
            f'<tr><td>{r["name"]}{mark}</td><td>{fmt(r.get("close"), 3)}</td>'
            f'<td class="{cls(r.get("dist_ma20_pct"))}">{pct(r.get("dist_ma20_pct"))}</td>'
            f'<td>{fmt(r.get("rsi6"), 1)}</td>'
            f'<td>{"✓" if r.get("ma5_gt_ma10") else "✗"}</td>'
            f'<td>{fmt(r.get("ma20"), 3)}</td><td>{sl_s}</td>'
            f'<td>{fmt(vr, 2) if vr else "[MISSING]"}</td>'
            f'<td>{r["status"]}</td></tr>\n'
        )

    TH = ('<tr><th>标的</th><th>现价(HK$)</th><th>距MA20%</th><th>RSI_6</th><th>MA5&gt;MA10</th>'
          '<th>确认触发价(MA20)</th><th>失效价(40日低)</th><th>量比</th><th>状态</th></tr>')

    if cands:
        t1 = "".join(track_row(r) for r in sorted(cands, key=lambda x: x["dist_ma20_pct"]))
        t1_title = f"回抽确认候选（{len(cands)} 只）"
    else:
        t1 = ('<tr><td colspan="9" style="text-align:left;padding:12px;">'
              '<b>本交易日无严格意义的回抽确认候选</b>：板块已整体站上 MA20，'
              '低于 MA20 的标的均处于 −1% 以内的贴近区间或未满足 MA5&gt;MA10 / RSI 40–58 条件，'
              '未形成“深跌后回抽”的结构。详见下表观察池。</td></tr>\n')
        t1_title = "回抽确认候选（0 只）"
    t2 = "".join(track_row(r) for r in sorted(watch, key=lambda x: x["dist_ma20_pct"])) or \
         '<tr><td colspan="9">本交易日观察池为空。</td></tr>\n'

    # ---------- 行动映射（按数据自动生成价位） ----------
    def act_line(r):
        sl = r.get("swing_low_40")
        sl_s = "[MISSING]" if (sl is None or sl == 0) else fmt(sl, 3)
        return f'{r["name"]}（触发 {fmt(r.get("ma20"), 3)}，失效 {sl_s}，距MA20 {pct(r.get("dist_ma20_pct"))}）'

    actions = ""
    if cands:
        actions += ('    <li><b>回抽确认候选（逢回踩分批，收盘站上 MA20 后加仓）：</b>'
                    + "；".join(act_line(r) for r in sorted(cands, key=lambda x: x["dist_ma20_pct"]))
                    + "。</li>\n")
    else:
        actions += ('    <li><b>回抽确认候选：</b>本交易日为 0 只——板块已整体站上 MA20，'
                    '不存在“深跌后回抽”的低吸结构。<b>不新建回抽仓，改为持有既有仓位 + 等回踩</b>。</li>\n')
    if watch:
        near = [r for r in watch if r["tier"] == "near"]
        others = [r for r in watch if r["tier"] != "near"]
        if near:
            actions += ('    <li><b>贴近 MA20 待确认（回踩不破即为最优买点，需等 MA5 上穿 MA10 确认）：</b>'
                        + "；".join(act_line(r) for r in sorted(near, key=lambda x: x["dist_ma20_pct"]))
                        + "。</li>\n")
        if others:
            actions += ('    <li><b>窗口内条件未满足 / 支撑企稳（观察，不急于动手）：</b>'
                        + "；".join(f'{r["name"]}（{r["status"]}，距MA20 {pct(r.get("dist_ma20_pct"))}）'
                                   for r in sorted(others, key=lambda x: x["dist_ma20_pct"]))
                        + "。</li>\n")
    if hots:
        actions += ('    <li><b>超买不追（持有 / 逢高减仓）：</b>'
                    + "；".join(f'{r["name"]}（距MA20 {pct(r.get("dist_ma20_pct"))}，RSI_6 {fmt(r.get("rsi6"), 1)}）'
                               for r in sorted(hots, key=lambda x: -(x.get("rsi6") or 0)))
                    + "——反弹幅度大、RSI 偏高，追高赔率差。</li>\n")
    if avoids:
        actions += ('    <li><b>规避（超卖反抽而非回抽确认）：</b>'
                    + "；".join(f'{r["name"]}（距MA20 {pct(r.get("dist_ma20_pct"))}，RSI_6 {fmt(r.get("rsi6"), 1)}）'
                               for r in avoids)
                    + "——空头排列或极端超卖，反弹不具备结构支撑。</li>\n")
    actions += ('    <li><b>失效规则（硬止损）：</b>任一持仓标的<b>收盘</b>跌破其近 40 日最低价（见第⑧节“失效价”列）'
                '→ 判定回抽失败，无条件离场，不做摊低成本。</li>\n')
    actions += (f'    <li><b>升级条件：</b>核心标的连续两日收盘站上 MA20 + 板块 20 日涨幅（当前 {pct(avg20)}）收敛转强 '
                f'+ 2Q26 中报验证基本面 → 上调评级；反之破位则下调。</li>\n')

    # ---------- 图表数据 ----------
    names = [r["name"] for r in rows]
    ytd = [r.get("chg_ytd") if r.get("chg_ytd") is not None else 0 for r in rows]
    dist = [r.get("dist_ma20_pct") if r.get("dist_ma20_pct") is not None else 0 for r in rows]
    pe_pairs = [(r["name"], r["pe_ratio"]) for r in rows
                if r.get("pe_ratio") is not None and 0 < r["pe_ratio"] < 500]
    pe_names = [p[0] for p in pe_pairs]
    pe_vals = [round(p[1], 1) for p in pe_pairs]
    sub_names = list(cfg["subgroups"].keys())
    sub_vals = []
    for g, members in cfg["subgroups"].items():
        vals = [r["chg_20d"] for r in rows if r["name"] in set(members) and r.get("chg_20d") is not None]
        sub_vals.append(round(statistics.mean(vals), 2) if vals else 0)

    n_pe_neg = sum(1 for r in rows if r.get("pe_ratio") is not None and r["pe_ratio"] < 0)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>港股{sector}板块深度分析 | {RUNDATE}</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">

<header>
  <h1>港股{sector}板块深度分析</h1>
  <div class="meta">运行日：{RUNDATE_DASH}（港股<b>收盘后</b>快照，HKT 16:00 后）｜数据来源：腾讯自选股 westock（行情/技术/K线原生支持 hkXXXXX 港股代码）；universe 由 <b>WebSearch 兜底构建</b>（westock data_sector 无港股板块分类）｜计价货币：<b>港元 HK$</b>｜样本：{len(rows)} 只</div>
</header>

<div class="card">
  <h2>① 摘要与 PM 七问</h2>
  <div class="rating-box"><b>整体评级：{cfg["rating_full"]}</b></div>
  <div class="kpi">
    <div><span class="sub">距MA20% 中位数</span><br><b class="{cls(med)}">{pct(med)}</b></div>
    <div><span class="sub">站上MA20 占比</span><br><b>{above_n}/{len(dists)}（{above_n / len(dists) * 100:.0f}%）</b></div>
    <div><span class="sub">板块20日均涨幅</span><br><b class="{cls(avg20)}">{pct(avg20)}</b></div>
    <div><span class="sub">板块5日均涨幅</span><br><b class="{cls(avg5)}">{pct(avg5)}</b></div>
    <div><span class="sub">当日均涨幅</span><br><b class="{cls(avgtd)}">{pct(avgtd)}</b></div>
    <div><span class="sub">回抽确认候选</span><br><b>{len(cands)} 只</b></div>
  </div>
  <p><b>一句话定位：</b>{cfg["oneline"]}</p>
  <p style="margin-top:8px;"><b>落后补涨（{lag_label}）：</b>{lag_txt}</p>
  <h3>PM 七问（变异认知）</h3>
  <ol>
{cfg["pm7"]}
  </ol>
</div>

<div class="card">
  <h2>② 板块定义与产业链地图</h2>
  <p>{cfg["chain_intro"]}</p>
  <p style="margin-top:10px;">{cfg["chain_map"]}</p>
</div>

<div class="card">
  <h2>③ 行业景气</h2>
  <ul>
{cfg["prosperity"]}
  </ul>
  <div id="chartSub" class="chart"></div>
  <p class="note">图1：产业链分层 20 日平均涨跌幅（数据：westock，{RUNDATE_DASH} 收盘）。</p>
</div>

<div class="card">
  <h2>④ 竞争格局与核心公司画像（行情 {RUNDATE_DASH} 收盘）</h2>
  <table>
    <tr><th>标的</th><th>代码</th><th>现价(HK$)</th><th>当日</th><th>20日</th><th>YTD</th><th>PE_ttm</th><th>距MA20%</th><th>技术状态</th></tr>
{core_rows}  </table>
  <p class="note">{cfg["core_note"]}</p>
</div>

<div class="card">
  <h2>⑤ 估值全景</h2>
  <p>{cfg["valuation"]}</p>
  <div id="chartVal" class="chart"></div>
  <p class="note">图2：有盈利样本 PE_ttm（港元计，剔除亏损与 PE&gt;500 极端值；本板块 {n_pe_neg} 只 PE 为负未入图）。PE_fwd 数据源未提供，标 [MISSING]，故仅列 ttm。</p>
</div>

<div class="card">
  <h2>⑥ 多空辩论</h2>
  <p class="bull"><b>Bull（多）：</b>{cfg["bull"]}</p>
  <p class="bear" style="margin-top:10px;"><b>Bear（空）：</b>{cfg["bear"]}</p>
</div>

<div class="card">
  <h2>⑦ 催化剂日历（未来 3–6 月）</h2>
  <ul>
{cfg["catalysts"]}
  </ul>
</div>

<div class="card">
  <h2>⑧ 个股回抽确认位跟踪（核心）</h2>
  <p><b>判定标准（港股适配）：</b>距 MA20 在 <b>−1%~−10%</b> 且 <b>RSI_6 40~58</b> 且 <b>MA5&gt;MA10</b> → 回抽确认候选；
  <b>确认触发价 = 收盘站上 MA20</b>；<b>失效价 = 近 40 日 K 线最低价（swing low）</b>——港股无“A 股 07-20 底”这类固定历史底概念，故改用 40 日摆动低点。
  距 MA20 在 −10%~−20% 归为“接近/支撑企稳”，&lt;−20% 或 RSI_6&lt;32 归为“超卖反抽”，不计入候选。</p>
  <h3>{t1_title}</h3>
  <table>
    {TH}
{t1}  </table>
  <h3>观察池：贴近MA20 / 窗口内条件未满足 / 支撑企稳（{len(watch)} 只）</h3>
  <table>
    {TH}
{t2}  </table>
  <p class="note">量比 = 当日成交量 ÷ 近 20 日均量，&lt;1 代表缩量。标 ⚠低流动 者为小市值低成交标的，仅适合极小仓位或直接规避。40 日最低价字段返回 0 的标 [MISSING] 并排除出候选判定。</p>
  <div id="chartDist" class="chart"></div>
  <p class="note">图3：距 MA20% 横向条形（红=回抽确认候选，灰=其他）。0 轴为 MA20 确认线。</p>
</div>

<div class="card">
  <h2>⑨ 结论与行动映射</h2>
  <div class="rating-box"><b>板块整体：{cfg["rating_full"]}</b></div>
  <p>{cfg["conclusion"]}</p>
  <ul>
{actions}  </ul>
</div>

<div class="card">
  <h2>⑩ 风险</h2>
  <ul>
{cfg["risks"]}
  </ul>
</div>

<div class="card">
  <h2>附图：样本 YTD 涨幅（港元计）</h2>
  <div id="chartYtd" class="chart"></div>
  <p class="note">图4：{len(rows)} 只样本年初至今涨跌幅（<b>红涨绿跌</b>，A 股习惯配色）。数据：westock，{RUNDATE_DASH} 收盘。</p>
</div>

<div class="disc"><b>本报告仅供研究参考，不构成个人投资建议。</b>数据来源：腾讯自选股 westock（行情/技术/K线，hkXXXXX 港股代码原生支持），universe 由 WebSearch 兜底构建（westock data_sector 无港股板块分类）；行业景气与催化剂来源已在正文逐条标注。所有价格与技术指标基于 {RUNDATE_DASH} <b>港股收盘</b>快照。2Q26 中报多数未披露，相关财务字段标 [MISSING]；PE_fwd 数据源未提供标 [MISSING]。失效价采用近 40 日 K 线最低价（港股适配），确认触发价为 MA20。计价单位为港元 HK$。</div>

</div>
<script>
var ytd = echarts.init(document.getElementById('chartYtd'));
var ytdNames = {json.dumps(names, ensure_ascii=False)};
var ytdData = {json.dumps(ytd)};
ytd.setOption({{tooltip:{{trigger:'axis',axisPointer:{{type:'shadow'}},formatter:function(p){{return p[0].name+'<br>YTD: '+(p[0].value>=0?'+':'')+p[0].value+'%';}}}},grid:{{left:95,right:60,top:20,bottom:30}},xAxis:{{type:'value',axisLabel:{{formatter:'{{value}}%'}}}},yAxis:{{type:'category',data:ytdNames.slice().reverse()}},series:[{{type:'bar',data:ytdData.slice().reverse(),itemStyle:{{color:function(p){{return p.value>=0?'#a32d2d':'#3b6d11';}}}},label:{{show:true,position:'right',formatter:function(p){{return (p.value>=0?'+':'')+p.value+'%';}},fontSize:11}}}}]}});

var sub = echarts.init(document.getElementById('chartSub'));
sub.setOption({{tooltip:{{trigger:'axis',axisPointer:{{type:'shadow'}},formatter:function(p){{return p[0].name+'<br>20日均值: '+(p[0].value>=0?'+':'')+p[0].value+'%';}}}},grid:{{left:70,right:40,top:20,bottom:80}},xAxis:{{type:'category',data:{json.dumps(sub_names, ensure_ascii=False)},axisLabel:{{rotate:22,fontSize:11,interval:0}}}},yAxis:{{type:'value',axisLabel:{{formatter:'{{value}}%'}}}},series:[{{type:'bar',data:{json.dumps(sub_vals)},itemStyle:{{color:function(p){{return p.value>=0?'#a32d2d':'#3b6d11';}}}},label:{{show:true,position:'top',formatter:function(p){{return (p.value>=0?'+':'')+p.value+'%';}},fontSize:12}}}}]}});

var vald = echarts.init(document.getElementById('chartVal'));
vald.setOption({{tooltip:{{trigger:'axis',axisPointer:{{type:'shadow'}},formatter:function(p){{return p[0].name+'<br>PE_ttm: '+p[0].value+'x';}}}},grid:{{left:60,right:30,top:20,bottom:90}},xAxis:{{type:'category',data:{json.dumps(pe_names, ensure_ascii=False)},axisLabel:{{rotate:42,fontSize:11,interval:0}}}},yAxis:{{type:'value',name:'PE_ttm(x)'}},series:[{{type:'bar',data:{json.dumps(pe_vals)},itemStyle:{{color:'#185fa5'}},label:{{show:true,position:'top',formatter:'{{c}}x',fontSize:10}}}}]}});

var dist = echarts.init(document.getElementById('chartDist'));
var distNames = {json.dumps(names, ensure_ascii=False)};
var distData = {json.dumps(dist)};
var candSet = {json.dumps({c: 1 for c in sorted(candset)}, ensure_ascii=False)};
dist.setOption({{tooltip:{{trigger:'axis',axisPointer:{{type:'shadow'}},formatter:function(p){{return p[0].name+'<br>距MA20: '+(p[0].value>=0?'+':'')+p[0].value+'%';}}}},grid:{{left:95,right:60,top:20,bottom:30}},xAxis:{{type:'value',axisLabel:{{formatter:'{{value}}%'}}}},yAxis:{{type:'category',data:distNames.slice().reverse()}},series:[{{type:'bar',data:distData.slice().reverse(),itemStyle:{{color:function(p){{return candSet[p.name]?'#a32d2d':'#999';}}}},label:{{show:true,position:'right',formatter:function(p){{return (p.value>=0?'+':'')+p.value+'%';}},fontSize:11}},markLine:{{silent:true,symbol:'none',data:[{{xAxis:0}}],lineStyle:{{color:'#185fa5',type:'solid'}}}}}}]}});

window.addEventListener('resize',function(){{ytd.resize();sub.resize();vald.resize();dist.resize();}});
</script>
</body>
</html>
"""
    out = os.path.join(BASE, f"港股{sector}板块深度分析_{RUNDATE}.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[OK] {out}  ({len(html)} bytes)")
    print(f"     距MA20中位数={med:+.2f}% 站上MA20={above_n}/{len(dists)} 20日均={avg20:+.2f}% "
          f"5日均={avg5:+.2f}% 当日均={avgtd:+.2f}% | 候选={len(cands)} 观察={len(watch)} 超买={len(hots)} 规避={len(avoids)}")
    print(f"     落后补涨({lag_label}): {lag_txt}")
    return {
        "name": f"港股{sector}", "sector": sector, "rating": cfg["rating"],
        "rating_full": cfg["rating_full"], "logic": cfg["push_logic"],
        "lag": lag_txt, "lag_label": lag_label, "path": out,
        "cands": [r["name"] for r in cands], "n_cand": len(cands),
        "median": round(med, 2), "above": above_n, "total": len(dists),
    }


if __name__ == "__main__":
    from hk_narratives import CONFIG
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    summary = []
    for s, c in CONFIG.items():
        if which not in ("all", s):
            continue
        summary.append(build(s, c))
    if which == "all":
        sp = os.path.join(DATA, "_hk_summary.json")
        with open(sp, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=1)
        print(f"\n[OK] summary -> {sp}")
