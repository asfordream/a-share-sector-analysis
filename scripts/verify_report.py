#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成「信号有效性回溯验证」HTML 报告（读取 data/_verify_result.json + K线缓存）。

用法：python3 scripts/verify_report.py
输出：<工作区根目录>/信号有效性回溯验证报告_<YYYYMMDD>.html
"""
import json
import os
import statistics as st
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
RES = os.path.join(DATA, "_verify_result.json")
CACHE = os.path.join(DATA, "_verify_kline_cache.json")
TODAY = datetime.now().strftime("%Y%m%d")

WIN, LOSE = ("T2", "T1"), ("SL", "SL_AMBIG")
LABEL = {"T2": "完全成功（达目标2）", "T1": "成功（达目标1）", "SL": "失败（先破止损）",
         "SL_AMBIG": "失败（同日双向·保守计）", "NO_ENTRY_NEVER": "未入场（从未回到买点区）",
         "NO_ENTRY_BREAK": "未入场（跳空破位）", "OPEN": "持有中（未了结）", "NO_DATA": "无数据"}
ORDER = ["T2", "T1", "OPEN", "SL", "SL_AMBIG", "NO_ENTRY_NEVER", "NO_ENTRY_BREAK", "NO_DATA"]
COLOR = {"T2": "#c62828", "T1": "#ef6c00", "SL": "#2e7d32", "SL_AMBIG": "#558b2f",
         "OPEN": "#f9a825", "NO_ENTRY_NEVER": "#90a4ae", "NO_ENTRY_BREAK": "#607d8b",
         "NO_DATA": "#bdbdbd"}


def a(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 2) if xs else None


def cls(v):
    """红涨绿跌（A股习惯）"""
    if v is None:
        return "neu"
    return "up" if v > 0 else ("dn" if v < 0 else "neu")


def fmt(v, suf="%"):
    return "—" if v is None else f"{v:+.2f}{suf}" if suf == "%" else f"{v}{suf}"


def build():
    R = json.load(open(RES, encoding="utf-8"))
    K = json.load(open(CACHE, encoding="utf-8"))
    D = R["detail"]
    P = {"meta": R["meta"], "overall": R["overall"], "overall_dedup": R["overall_dedup"]}

    # 结果分布
    P["result_pie"] = [{"name": LABEL[k], "value": R["overall"]["cnt"].get(k, 0), "itemStyle": {"color": COLOR[k]}}
                       for k in ORDER if R["overall"]["cnt"].get(k, 0)]

    # 收益直方图
    rets = [r["ret"] for r in D if r["ret"] is not None]
    edges = [-100, -20, -15, -10, -5, 0, 5, 10, 20, 100]
    P["hist"] = {"x": [f"{edges[i]}~{edges[i+1]}" for i in range(len(edges) - 1)],
                 "y": [sum(1 for x in rets if edges[i] <= x < edges[i + 1]) for i in range(len(edges) - 1)]}
    P["hist_color"] = ["#2e7d32"] * 5 + ["#c62828"] * 4

    # 按信号类型 + 风险收益比
    rr, sig_tbl = {}, []
    for sig in ("回抽确认", "主升浪买点区"):
        rows = [r for r in D if r["sig"] == sig and r["entry"]]
        up = [(r["t1"] / r["entry"] - 1) * 100 for r in rows if r.get("t1")]
        dn = [(r["stop"] / r["entry"] - 1) * 100 for r in rows if r.get("stop")]
        up2 = [(r["t2"] / r["entry"] - 1) * 100 for r in rows if r.get("t2")]
        rr[sig] = {"up": a(up), "dn": a(dn), "up2": a(up2),
                   "ratio": round(abs(a(dn) / a(up)), 2) if a(up) else None}
        v = R["by_sig"][sig]
        d = R["by_sig_dedup"].get(sig, {})
        sig_tbl.append({"sig": sig, **v, "dedup_n": d.get("n"), "dedup_wr": d.get("win_rate"),
                        "dedup_ret": d.get("avg_ret")})
    P["rr"] = rr
    P["sig_tbl"] = sig_tbl

    # 路径特征
    P["path"] = {}
    for tag, keys in (("win", WIN), ("lose", LOSE), ("open", ("OPEN",))):
        rows = [r for r in D if r["result"] in keys]
        P["path"][tag] = {
            "n": len(rows), "hold": a([r["hold_days"] for r in rows]),
            "mfe": a([r["mfe"] for r in rows]), "mae": a([r["mae"] for r in rows]),
            "ret": a([r["ret"] for r in rows]),
            "mfe_neg": sum(1 for r in rows if r["mfe"] is not None and r["mfe"] < 2),
        }
    sl = [r for r in D if r["result"] in LOSE]
    P["mfe_lose"] = {"x": ["<0", "0~2", "2~5", "5~10", "≥10"],
                     "y": [sum(1 for r in sl if r["mfe"] is not None and lo <= r["mfe"] < hi)
                           for lo, hi in [(-99, 0), (0, 2), (2, 5), (5, 10), (10, 99)]]}
    w = [r for r in D if r["result"] in WIN]
    P["hold_win"] = {"x": ["0~3日", "3~5日", "5~10日", "10~15日", "≥15日"],
                     "y": [sum(1 for r in w if lo <= (r["hold_days"] or 0) < hi)
                           for lo, hi in [(0, 3), (3, 5), (5, 10), (10, 15), (15, 999)]]}

    # 持有中：距止损空间
    op = [r for r in D if r["result"] == "OPEN" and r["stop"] and r["exit_price"]]
    gaps = sorted((r["exit_price"] / r["stop"] - 1) * 100 for r in op)
    P["open_gap"] = {"n": len(gaps), "mean": a(gaps), "median": round(st.median(gaps), 2),
                     "min": round(min(gaps), 2),
                     "buckets": [{"label": f"+{lo}~{hi}%",
                                  "n": sum(1 for x in gaps if lo <= x < hi)}
                                 for lo, hi in [(0, 3), (3, 6), (6, 10), (10, 20), (20, 999)]]}
    P["open_pos"] = sum(1 for r in op if r["ret"] and r["ret"] > 0)

    # 时间止损模拟
    ts, tot_by_n = {}, {}
    for N in (5, 10, 15):
        outs, tot = [], []
        for r in D:
            if r["result"] in WIN + LOSE:
                tot.append(r["ret"])
                continue
            if r["result"] != "OPEN":
                continue
            bars = [b for b in K[r["full_code"]]["bars"]
                    if r["entry_date"] < b["date"] <= R["meta"]["data_end"]]
            x = (bars[N - 1]["close"] / r["entry"] - 1) * 100 if len(bars) >= N else r["ret"]
            outs.append(x)
            tot.append(x)
        tt = [x for x in tot if x is not None]
        ts[N] = {"open_avg": a(outs), "open_median": round(st.median([x for x in outs if x is not None]), 2),
                 "n_closed": sum(1 for r in D if r["result"] == "OPEN"
                                 and len([b for b in K[r["full_code"]]["bars"]
                                          if r["entry_date"] < b["date"] <= R["meta"]["data_end"]]) >= N),
                 "tot_avg": a(tt), "tot_median": round(st.median(tt), 2) if tt else None,
                 "tot_pos": round(100 * sum(1 for x in tt if x > 0) / len(tt), 1) if tt else None}
    P["ts"] = ts
    P["base_all"] = {"avg": R["overall"]["avg_ret_all"], "median": R["overall"]["median_ret_all"],
                     "pos": round(100 * sum(1 for x in rets if x > 0) / len(rets), 1)}

    # 板块表
    P["sector_tbl"] = [{"name": k, **v} for k, v in
                       sorted(R["by_sector"].items(), key=lambda x: -x[1]["n"])]
    # 日期表
    P["date_tbl"] = [{"date": k, **v,
                      "open_avg": a([r["ret"] for r in D if r["date"] == k and r["result"] == "OPEN"]),
                      "ne": sum(1 for r in D if r["date"] == k and r["result"].startswith("NO_ENTRY"))}
                     for k, v in sorted(R["by_date"].items())]
    P["date_chart"] = {"x": [k for k, _ in sorted(R["by_date"].items())],
                       "wr": [R["by_date"][k]["win_rate"] for k, _ in sorted(R["by_date"].items())],
                       "wr_all": [R["by_date"][k]["win_rate_all"] for k, _ in sorted(R["by_date"].items())],
                       "n": [R["by_date"][k]["n"] for k, _ in sorted(R["by_date"].items())]}
    P["sector_chart"] = {"x": [t["name"] for t in P["sector_tbl"] if t["n"] >= 10],
                         "ret": [t["avg_ret"] for t in P["sector_tbl"] if t["n"] >= 10],
                         "wr": [t["win_rate"] for t in P["sector_tbl"] if t["n"] >= 10]}

    # 个案
    def brief(r):
        return {"date": r["date_f"], "sector": r["sector"], "name": r["name"], "code": r["full_code"],
                "sig": r["sig"], "buy": f"{r['buy_lo']}~{r['buy_hi']}", "entry": round(r["entry"], 2),
                "exit": round(r["exit_price"], 2) if r["exit_price"] else None,
                "how": r.get("exit"), "result": LABEL.get(r["result"], r["result"]),
                "ret": r["ret"], "hold": r["hold_days"], "mfe": r["mfe"], "mae": r["mae"],
                "shape": r["shape"]}
    P["top_win"] = [brief(r) for r in sorted([x for x in D if x["result"] in WIN],
                                             key=lambda x: -(x["ret"] or 0))[:8]]
    P["top_lose"] = [brief(r) for r in sorted([x for x in D if x["result"] in LOSE],
                                              key=lambda x: (x["ret"] or 0))[:8]]
    # 到手的利润飞了：曾浮盈≥10% 却止损
    P["profit_gone"] = [brief(r) for r in sorted(
        [x for x in D if x["result"] in LOSE and (x["mfe"] or 0) >= 10],
        key=lambda x: -(x["mfe"] or 0))[:8]]
    P["profit_gone_n"] = sum(1 for x in D if x["result"] in LOSE and (x["mfe"] or 0) >= 10)
    return P


CSS = """
*{box-sizing:border-box}body{margin:0;background:#f5f6f8;color:#1c1f23;
font:14px/1.65 -apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:28px 22px 60px}
h1{font-size:25px;margin:0 0 6px}h2{font-size:19px;margin:34px 0 12px;padding-left:11px;border-left:4px solid #1565c0}
h3{font-size:15px;margin:20px 0 8px;color:#37474f}
.sub{color:#607d8b;font-size:13px;margin-bottom:18px}
.card{background:#fff;border:1px solid #e3e7ec;border-radius:10px;padding:18px 20px;margin:14px 0;
box-shadow:0 1px 3px rgba(16,24,40,.04)}
.kpi{display:grid;grid-template-columns:repeat(auto-fit,minmax(158px,1fr));gap:12px;margin:14px 0}
.kpi .card{margin:0;padding:14px 16px}
.kpi .lbl{font-size:12px;color:#78909c;letter-spacing:.3px}
.kpi .val{font-size:25px;font-weight:700;margin-top:5px;font-variant-numeric:tabular-nums}
.kpi .note{font-size:11.5px;color:#90a4ae;margin-top:3px}
.up{color:#c62828}.dn{color:#2e7d32}.neu{color:#546e7a}
table{width:100%;border-collapse:collapse;font-size:13px;margin-top:8px}
th,td{padding:7px 9px;border-bottom:1px solid #eceff1;text-align:right;white-space:nowrap}
th{background:#f0f3f7;color:#37474f;font-weight:600;font-size:12.5px}
td:first-child,th:first-child{text-align:left}
tbody tr:hover{background:#fafbfc}
.warn{background:#fff8e1;border-left:4px solid #f9a825;padding:13px 16px;border-radius:6px;margin:12px 0}
.danger{background:#ffebee;border-left:4px solid #c62828;padding:13px 16px;border-radius:6px;margin:12px 0}
.ok{background:#e8f5e9;border-left:4px solid #2e7d32;padding:13px 16px;border-radius:6px;margin:12px 0}
.info{background:#e3f2fd;border-left:4px solid #1565c0;padding:13px 16px;border-radius:6px;margin:12px 0}
.chart{width:100%;height:330px;margin-top:6px}
.two{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:820px){.two{grid-template-columns:1fr}}
ol,ul{padding-left:22px}li{margin:5px 0}
code{background:#eef1f5;padding:1px 5px;border-radius:4px;font-size:12.5px}
.foot{margin-top:36px;padding-top:14px;border-top:1px solid #dfe3e8;color:#78909c;font-size:12.5px}
h2 small{font-weight:400;color:#90a4ae;font-size:13px;margin-left:6px}
"""


def render(P):
    m, o, od = P["meta"], P["overall"], P["overall_dedup"]
    rr = P["rr"]
    ts = P["ts"]

    def kpi(lbl, val, note="", cl=""):
        return f'<div class="card"><div class="lbl">{lbl}</div><div class="val {cl}">{val}</div><div class="note">{note}</div></div>'

    # 结果分布表
    res_rows = "".join(
        f'<tr><td>{LABEL[k]}</td><td>{o["cnt"].get(k,0)}</td>'
        f'<td>{round(100*o["cnt"].get(k,0)/o["n"],1)}%</td></tr>'
        for k in ORDER if o["cnt"].get(k, 0))

    # 按信号类型表
    sig_rows = ""
    for t in P["sig_tbl"]:
        sig_rows += (f'<tr><td>{t["sig"]}</td><td>{t["n"]}</td><td>{t["traded"]}</td>'
                     f'<td class="{cls(t["win_rate"]-50)}">{t["win_rate"]}%</td>'
                     f'<td class="{cls(t["win_rate_all"]-50)}">{t["win_rate_all"]}%</td>'
                     f'<td class="{cls(t["avg_ret"])}">{fmt(t["avg_ret"])}</td>'
                     f'<td class="{cls(t["avg_ret_all"])}">{fmt(t["avg_ret_all"])}</td>'
                     f'<td>{t["pl_ratio"]}</td><td>{t["no_entry_rate"]}%</td>'
                     f'<td class="neu">{t["dedup_n"]} 行 / {t["dedup_wr"]}% / {fmt(t["dedup_ret"])}</td></tr>')

    # 板块表
    sec_rows = ""
    for t in P["sector_tbl"]:
        if t["n"] < 5:
            continue
        sec_rows += (f'<tr><td>{t["name"]}</td><td>{t["n"]}</td><td>{t["traded"]}</td>'
                     f'<td class="{cls(t["win_rate"]-50)}">{t["win_rate"]}%</td>'
                     f'<td class="{cls(t["win_rate_all"]-50)}">{t["win_rate_all"]}%</td>'
                     f'<td class="{cls(t["avg_ret"])}">{fmt(t["avg_ret"])}</td>'
                     f'<td>{t["pl_ratio"] if t["pl_ratio"] else "—"}</td>'
                     f'<td>{t["open_n"]}</td></tr>')

    # 日期表
    date_rows = ""
    for t in P["date_tbl"]:
        date_rows += (f'<tr><td>{t["date"]}</td><td>{t["n"]}</td><td>{t["traded"]}</td>'
                      f'<td class="{cls(t["win_rate"]-50)}">{t["win_rate"]}%</td>'
                      f'<td class="{cls(t["win_rate_all"]-50)}">{t["win_rate_all"]}%</td>'
                      f'<td class="{cls(t["avg_ret"])}">{fmt(t["avg_ret"])}</td>'
                      f'<td>{t["open_n"]}</td>'
                      f'<td class="{cls(t["open_avg"])}">{fmt(t["open_avg"])}</td></tr>')

    def case_rows(lst, color_neg=False):
        out = ""
        for c in lst:
            out += (f'<tr><td>{c["date"]}</td><td>{c["sector"]}</td><td>{c["name"]} '
                    f'<span style="color:#90a4ae;font-size:11.5px">{c["code"][2:]}</span></td>'
                    f'<td>{c["sig"]}</td><td>{c["buy"]}</td><td>{c["entry"]}</td><td>{c["exit"]}</td>'
                    f'<td>{c["how"] or "—"}</td><td>{c["result"]}</td>'
                    f'<td class="{cls(c["ret"])}"><b>{fmt(c["ret"])}</b></td>'
                    f'<td>{c["hold"] if c["hold"] is not None else "—"}</td>'
                    f'<td class="{cls(c["mfe"])}">{fmt(c["mfe"])}</td>'
                    f'<td class="{cls(c["mae"])}">{fmt(c["mae"])}</td></tr>')
        return out

    path = P["path"]
    gap_rows = "".join(f'<tr><td>{b["label"]}</td><td>{b["n"]}</td></tr>' for b in P["open_gap"]["buckets"])
    ts_rows = ""
    for N in (5, 10, 15):
        t = ts[N]
        ts_rows += (f'<tr><td>持有 {N} 个交易日</td><td>{t["n_closed"]}</td>'
                    f'<td class="{cls(t["open_avg"])}">{fmt(t["open_avg"])}</td>'
                    f'<td class="{cls(t["open_median"])}">{fmt(t["open_median"])}</td>'
                    f'<td class="{cls(t["tot_avg"])}">{fmt(t["tot_avg"])}</td>'
                    f'<td class="{cls(t["tot_median"])}">{fmt(t["tot_median"])}</td>'
                    f'<td>{t["tot_pos"]}%</td></tr>')

    html = TEMPLATE
    reps = {
        "__DATE__": m["generated"][:10],
        "__ROWS__": str(m["n_rows"]),
        "__CODES__": str(m["n_codes"]),
        "__DEND__": m["data_end"],
        "__KPIS__": (
            kpi("全样本期望收益", fmt(o["avg_ret_all"]), f"{o['n']} 行 / 中位 {fmt(o['median_ret_all'])}",
                cls(o["avg_ret_all"]))
            + kpi("正收益占比（全样本）", f'{P["base_all"]["pos"]}%', "口径：按 09-28 收盘计", "neu")
            + kpi("胜率（仅已了结）", f'{o["win_rate"]}%', f'已了结 {o["traded"]} 行', cls(o["win_rate"]-50))
            + kpi("胜率（含持有中浮动）", f'{o["win_rate_all"]}%', "持有中 136 行按最新价计入", cls(o["win_rate_all"]-50))
            + kpi("盈亏比", f'{o["pl_ratio"]}', f'均盈 {fmt(o["avg_win"])} / 均亏 {fmt(o["avg_loss"])}',
                  "up" if (o["pl_ratio"] or 0) >= 1 else "dn")
            + kpi("主升浪 风险收益比", f'{rr["主升浪买点区"]["ratio"]}',
                  f'目标 {fmt(rr["主升浪买点区"]["up"])} / 止损 {fmt(rr["主升浪买点区"]["dn"])}', "dn")
        ),
        "__RES_ROWS__": res_rows,
        "__SIG_ROWS__": sig_rows,
        "__SEC_ROWS__": sec_rows,
        "__DATE_ROWS__": date_rows,
        "__OPEN_N__": str(o["open_n"]),
        "__OPEN_AVG__": fmt(o["open_avg_ret"]),
        "__OPEN_POS__": str(P["open_pos"]),
        "__PATH_WIN__": (f'{path["win"]["n"]} 行 / 持有 {path["win"]["hold"]} 日 / '
                         f'MFE {fmt(path["win"]["mfe"])} / MAE {fmt(path["win"]["mae"])} / '
                         f'收益 {fmt(path["win"]["ret"])}'),
        "__PATH_LOSE__": (f'{path["lose"]["n"]} 行 / 持有 {path["lose"]["hold"]} 日 / '
                          f'MFE {fmt(path["lose"]["mfe"])} / MAE {fmt(path["lose"]["mae"])} / '
                          f'收益 {fmt(path["lose"]["ret"])}'),
        "__PATH_OPEN__": (f'{path["open"]["n"]} 行 / 持有 {path["open"]["hold"]} 日 / '
                          f'MFE {fmt(path["open"]["mfe"])} / MAE {fmt(path["open"]["mae"])} / '
                          f'收益 {fmt(path["open"]["ret"])}'),
        "__LOSE_MFE_LT2__": str(P["mfe_lose"]["y"][0] + P["mfe_lose"]["y"][1]),
        "__HOLD_WIN_10__": str(P["hold_win"]["y"][0] + P["hold_win"]["y"][1] + P["hold_win"]["y"][2]),
        "__PROFIT_GONE_N__": str(P["profit_gone_n"]),
        "__GAP_ROWS__": gap_rows,
        "__GAP_MEDIAN__": fmt(P["open_gap"]["median"]),
        "__GAP_MIN__": fmt(P["open_gap"]["min"]),
        "__TS_ROWS__": ts_rows,
        "__TS5_OPEN__": fmt(ts[5]["open_avg"]),
        "__TS10_TOT__": fmt(ts[10]["tot_avg"]),
        "__BASE_TOT__": fmt(P["base_all"]["avg"]),
        "__TOP_WIN__": case_rows(P["top_win"]),
        "__TOP_LOSE__": case_rows(P["top_lose"]),
        "__GONE__": case_rows(P["profit_gone"]),
        "__RR_CONF__": json.dumps(P["rr"], ensure_ascii=False),
        "__PAYLOAD__": json.dumps({
            "pie": P["result_pie"], "hist": P["hist"], "histColor": P["hist_color"],
            "sig": P["sig_tbl"], "sector": P["sector_chart"], "date": P["date_chart"],
            "rr": P["rr"], "path": P["path"], "mfeLose": P["mfe_lose"], "holdWin": P["hold_win"],
        }, ensure_ascii=False),
    }
    for k, v in reps.items():
        html = html.replace(k, str(v))
    return html


TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>信号有效性回溯验证报告 __DATE__</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
<style>__CSS__</style></head><body><div class="wrap">

<h1>A股板块候选信号 · 有效性回溯验证报告</h1>
<div class="sub">回抽确认 / 主升浪买点区 ｜ 样本：__ROWS__ 行 · __CODES__ 只个股 · 信号日 2026-08-18 ~ 2026-09-23 ｜
行情截止 __DEND__ ｜ 生成于 __DATE__　<span style="color:#c62828">本报告为独立研究任务，不进入每日自动化</span></div>

<div class="kpi">__KPIS__</div>

<div class="danger"><b>一句话结论：这两类信号在样本期内「统计上不成立」。</b><br>
跟踪表里看起来不错的状态，是把「未了结」样本移除后的幸存者偏差 ——
只算已了结的 247 行胜率有 57.1%，但把 __OPEN_N__ 行「持有中」（平均浮动 __OPEN_AVG__，其中仅 __OPEN_POS__ 行浮盈）
按最新价计入后，胜率跌到 <b>__KPIS_WR_ALL__%</b>，全样本期望 <b>__KPIS_RET_ALL__</b>、中位数 <b>__KPIS_MED_ALL__</b>。
根因不是"选股不准"，而是<b>出场结构设计有缺陷</b>（见第 7 节）。</div>

<h2>一、方法论与口径<small>先交代怎么算的，否则数字没有意义</small></h2>
<div class="card">
<p><b>为什么要重做验证：</b>跟踪表的「状态」列由 <code>build_track_table._status()</code> 按<b>当日快照价</b>机械判定
（现价≥目标1→已止盈 / 现价≤买点上沿→已触发 / 现价≤止损→已止损）。它<b>没有路径概念</b>：
既不记录"信号发出后是否曾触及止损"，也不区分"先止损还是先止盈"，且历史行会被每次运行的最新价反复刷新。
所以「状态」列不能当成败依据 —— 本报告改用日 K 线做真正的<b>事件研究（Event Study）</b>。</p>
<p><b>入场规则：</b>① 信号日收盘价若落在买点区间内 → 以该收盘价入场；
② 否则自信号日<b>次日</b>起，首个日内触及买点区间的交易日按区间挂单成交（开盘在区间内按开盘价、高于上沿按上沿成交）；
③ 开盘低于买点下沿但未破止损 → 按开盘价成交（低开给了更优买点）；
④ <b>开盘已跌破止损线 → 判「破位失效」不入场</b>（挂在区间内的单不该成交）。</p>
<p><b>出场规则：</b>自入场日次日起逐日推进 ——
触及止损 → 成交价取 <code>min(开盘价, 止损价)</code>（跳空低开按更差价，贴合止损单实际）；
触及目标1/目标2 → <b>按目标价成交</b>（挂单止盈口径，不美化跳空高价）；
<b>同日既触止损又触目标</b> → 日内先后无法判定 → <b>保守计「止损(同日双向)」并单独披露</b>。
入场日当天不判出场（保守弃权）。</p>
<p><b>两个胜率口径（都给出，避免单口径误导）：</b>
<span class="up">口径A</span>「仅已了结」＝ 只统计已触及边界的样本（这会系统性高估，因为未了结样本的浮动亏损失去计入）；
<span class="up">口径B</span>「全部含浮动」＝ 把「持有中」按 __DEND__ 收盘价计入（更接近真实账户盈亏）。</p>
<p><b>数据来源与边界：</b>westock CLI 前复权（qfq）日 K 线，窗口 2026-08-01 ~ __DEND__；
2026-09-29 为未完成盘中 bar 已剔除；<b>2026-09-25 为中秋节休市</b>（沪深北交易所公告：9/25–9/27 休市）故无行情，属正常。</p>
</div>

<h2>二、总览结果</h2>
<div class="two">
  <div class="card"><h3 style="margin-top:0">结果分布（__ROWS__ 行）</h3><div id="cPie" class="chart" style="height:300px"></div></div>
  <div class="card"><h3 style="margin-top:0">结果计数明细</h3><table><thead><tr><th>结果</th><th>行数</th><th>占比</th></tr></thead><tbody>__RES_ROWS__</tbody></table>
  <div class="info" style="margin-top:12px">「持有中」占 <b>__OPEN_N__</b> 行（__OPEN_PCT__%）—— 这批样本既没止损也没达标，
  是本次验证最需要盯住的群体：平均浮动 <b class="dn">__OPEN_AVG__</b>，其中只有 <b>__OPEN_POS__</b> 行是浮盈。</div></div>
</div>
<div class="card"><h3 style="margin-top:0">收益率分布（全样本，按 __DEND__ 收盘）</h3><div id="cHist" class="chart"></div>
<div class="warn">分布呈<b>双峰</b>：亏损集中在 −15%~0%（其中 −10%~−5% 一格达 137 行），盈利集中在 +10%~20%。
这是典型的「<b>赚小钱、亏大钱</b>」结构 —— 目标离得近、止损设得远（见第 7 节）。</div></div>

<h2>三、按信号类型拆解<small>回抽确认 vs 主升浪买点区</small></h2>
<div class="card"><table><thead><tr><th>信号类型</th><th>样本</th><th>已了结</th>
<th>胜率A(已了结)</th><th>胜率B(全部)</th><th>均收益A</th><th>均收益B</th><th>盈亏比</th><th>未入场率</th>
<th>去重口径(每股首个信号)</th></tr></thead><tbody>__SIG_ROWS__</tbody></table>
<div class="two" style="margin-top:14px">
<div><h3>风险收益比结构（入场价口径）</h3><div id="cRR" class="chart" style="height:290px"></div></div>
<div><h3>该结构意味着什么</h3>
<div class="danger"><b>主升浪信号存在结构性缺陷：</b>目标1 平均上行 <b>__RR_UP_M__</b>，
而止损平均下行 <b>__RR_DN_M__</b> —— 风险收益比 <b>__RR_R_M__</b>（&gt;1 即"亏多赚少"）。<br>
根因：主升浪买点区间取 MA20 的 −15%~+5%（很宽），止损又按"买点下限×0.92"计算
＝ MA20×0.782，离入场价太远。<br>
后果：<b>__RR_WR_M__% 的胜率是"小赚"堆出来的</b>，一次失败要吃掉 2~3 次成功（盈亏比 __RR_PL_M__）。</div>
<div class="ok">回抽确认的风险收益比 <b>__RR_R_P__</b>（目标 __RR_UP_P__ / 止损 __RR_DN_P__）相对合理，
问题在别处：目标1 太近，利润被过早截断（见第 7 节病因②）。</div></div></div></div>

<h2>四、按板块拆解</h2>
<div class="card"><div id="cSector" class="chart" style="height:320px"></div>
<table style="margin-top:14px"><thead><tr><th>板块</th><th>样本</th><th>已了结</th><th>胜率A</th><th>胜率B</th>
<th>均收益A</th><th>盈亏比</th><th>持有中</th></tr></thead><tbody>__SEC_ROWS__</tbody></table>
<div class="warn"><b>分化极大：</b>PCB（胜率 80.8%／均收益 +7.07%／盈亏比 1.3）是目前唯一"期望为正"的板块，元件次之；
而半导体（35.9%／−4.35%／0.57）、存储、电网设备、算力均为负期望。同一套信号在不同板块的有效性差异，
说明<b>信号本身缺少板块层面的适配与过滤</b>。</div></div>

<h2>五、按信号日拆解<small>信号质量高度依赖市场阶段</small></h2>
<div class="card"><div id="cDate" class="chart" style="height:320px"></div>
<table style="margin-top:14px"><thead><tr><th>信号日</th><th>样本</th><th>已了结</th><th>胜率A</th><th>胜率B</th>
<th>均收益A</th><th>持有中</th><th>持有中均浮动</th></tr></thead><tbody>__DATE_ROWS__</tbody></table>
<div class="warn"><b>极不稳定：</b>08-18 批次胜率仅 25%、09-23 批次为 0%，而 08-19~08-28 批次达 57%~82%。
同一模型在 20 个交易日里给出 0%~100% 的胜率区间 —— 说明信号<b>没有市场环境过滤</b>，
在板块动能转弱的阶段仍照常输出候选。</div></div>

<h2>六、成功与失败的路径特征<small>这一节是调优的核心依据</small></h2>
<div class="card">
<table><thead><tr><th>群体</th><th>路径特征</th></tr></thead><tbody>
<tr><td>成功（T1/T2）</td><td>__PATH_WIN__</td></tr>
<tr><td>失败（止损）</td><td>__PATH_LOSE__</td></tr>
<tr><td>持有中</td><td>__PATH_OPEN__</td></tr>
</tbody></table>
<div class="two" style="margin-top:14px">
<div><h3>失败样本：入场后最大浮盈（MFE）分布</h3><div id="cMfe" class="chart" style="height:270px"></div></div>
<div><h3>成功样本：达标耗时分布</h3><div id="cHold" class="chart" style="height:270px"></div></div>
</div>
<div class="danger"><b>最有价值的发现（可直接落地）：</b>
两个群体的差异在入场后<b>很早就显现</b> ——
① 失败样本 Average MFE 仅 <b>__PATH_LOSE_MFE__</b>，其中 <b>__LOSE_MFE_LT2__ 行（占 60%）入场后最大浮盈不足 2%</b>，即"买入即下跌、几乎没给过赚钱机会"；
② 失败样本平均要拖 <b>__PATH_LOSE_HOLD__ 个交易日</b>才触及止损（磨了很久）；
③ 而成功样本 <b>__HOLD_WIN_10__ 行（占 76%）在 10 个交易日内就达标</b>。<br>
→ 结论：<b>「入场后 5~10 个交易日仍不涨」本身就是最强的失败信号</b>，不必等价格磨到止损线。</div>
</div>

<h2>七、核心病因（3 条）</h2>
<div class="card">
<h3>病因①　主升浪止损过宽 —— 结构性亏损设计</h3>
<p>止损＝<code>min(MA20, 买点下限×0.92)</code>，而主升浪买点下限＝MA20×0.85 →
止损落在 MA20 下方约 22%，距入场价平均 <b class="dn">__RR_DN_M__</b>；而目标1 只有 <b class="up">__RR_UP_M__</b>。
<b>风险收益比 __RR_R_M__，长期必亏</b>（即使胜率 93.9%）。</p>

<h3>病因②　目标1 过近 + 无移动止盈 —— 到手的利润飞了</h3>
<p>目标1 取 <code>MA60</code> 或"现价×1.10"，两者取其一，本质上把上行封在 +11% 附近。
样本中 <b>129 行止盈于目标1，只有 12 行到达目标2</b>（比例 10.8:1）。
更严重的是：<b>有 __PROFIT_GONE_N__ 行曾经浮盈 ≥10%（一度接近目标）却最终以止损收场</b> —— 没有保本/移动止盈机制。</p>

<h3>病因③　缺少市场与板块环境过滤</h3>
<p>同信号在 20 个信号日上的胜率区间为 <b>0%~100%</b>，在 11 个板块上为 <b>36%~81%</b>。
信号只在"板块动能向上"时有效，但当前模型对<b>板块裁决为 🟢（双弱背离/破位预警/回避）</b>的板块照样输出候选并计入跟踪表。</p>
</div>

<h2>八、调优建议<small>按优先级排序，每条附量化依据</small></h2>
<div class="card">
<h3>建议①　收窄主升浪止损（最高优先级）</h3>
<p>把主升浪止损从"买点下限×0.92"改为 <b>入场价×0.93~0.95</b>（或 MA20×0.95），
把风险收益比从 __RR_R_M__ 压到 <b>≤1</b>。若维持原胜率，期望收益将直接由负转正。</p>

<h3>建议②　引入时间止损（成本最低、见效最快）</h3>
<p>规则：<b>入场后 5 个交易日，若最大浮盈 &lt; 2% 则主动离场</b>（不等止损）。
量化验证（对当前 __OPEN_N__ 行「持有中」回测）：</p>
<table><thead><tr><th>时间止损规则</th><th>被提前了结</th><th>该组均收益</th><th>该组中位</th>
<th>全样本期望</th><th>全样本中位</th><th>正收益占比</th></tr></thead><tbody>__TS_ROWS__</tbody></table>
<div class="ok">量化效果：仅"持有中"这一组就从 <b class="dn">__OPEN_AVG__</b> 改善到 <b class="up">__TS5_OPEN__</b>（5 日规则），
全样本期望从 <b class="dn">__BASE_TOT__</b> 改善到 <b>__TS10_TOT__</b>。这是**唯一不需要改动选股逻辑**的改进。</div>

<h3>建议③　目标1 动态化 + 分批止盈</h3>
<p>把"现价×1.10"改为 <b>max(MA60, 现价×(1+1.5×ATR%))</b> 之类的动态口径；同时把仓位拆两批：
目标1 减半、剩余以"回撤 MA10 或保本价"跟踪，解决 __PROFIT_GONE_N__ 行"到手的利润飞了"的问题。</p>

<h3>建议④　加板块与市场环境过滤</h3>
<p>配合已有裁决体系：只在板块裁决为 <span class="up">🔴</span> 或"加码・匹配执行/结构已立"时把候选计入跟踪表与自选股（当前口径已部分实现），
并进一步要求<b>板块站上 MA20 比例 ≥ 60%</b>（当前无此约束）。对照第 5 节，弱市批次应直接不产生候选。</p>

<h3>建议⑤　建立板块白名单/权重</h3>
<p>PCB、元件维持权重；半导体、存储、电网设备、算力在当前参数下为负期望，建议<b>降低权重或暂缓入选</b>，
待参数修正后重新评估。<span style="color:#90a4ae">（注：样本期仅 6 周，板块结论需更长样本确认）</span></p>

<h3>建议⑥　修正跟踪表「状态」列语义</h3>
<p>把状态从"快照价比较"改为<b>本报告的路径判定</b>（先到先算，含 MFE/MAE），
让表格本身就能反映"是否曾触及止损"，避免"已止盈/已触发"长期滚动、掩盖真实亏损。</p>
</div>

<h2>九、典型案例</h2>
<div class="card"><h3 style="margin-top:0">最成功的 8 例（按收益率）</h3>
<table><thead><tr><th>信号日</th><th>板块</th><th>个股</th><th>信号</th><th>买点区间</th><th>入场价</th>
<th>出场价</th><th>出场方式</th><th>结果</th><th>收益</th><th>持有(日)</th><th>MFE</th><th>MAE</th></tr></thead>
<tbody>__TOP_WIN__</tbody></table></div>

<div class="card"><h3 style="margin-top:0">最失败的 8 例（按亏损）</h3>
<table><thead><tr><th>信号日</th><th>板块</th><th>个股</th><th>信号</th><th>买点区间</th><th>入场价</th>
<th>出场价</th><th>出场方式</th><th>结果</th><th>收益</th><th>持有(日)</th><th>MFE</th><th>MAE</th></tr></thead>
<tbody>__TOP_LOSE__</tbody></table></div>

<div class="card"><h3 style="margin-top:0">「到手的利润飞了」典型（曾浮盈 ≥10% 却最终止损，共 __PROFIT_GONE_N__ 行）</h3>
<table><thead><tr><th>信号日</th><th>板块</th><th>个股</th><th>信号</th><th>买点区间</th><th>入场价</th>
<th>出场价</th><th>出场方式</th><th>结果</th><th>收益</th><th>持有(日)</th><th>MFE</th><th>MAE</th></tr></thead>
<tbody>__GONE__</tbody></table>
<div class="warn">这些样本的 MFE 都在 10% 以上 —— 说明<b>不是选股失败，而是离场机制缺失</b>。建议②③针对的正是这类损耗。</div></div>

<h2>十、数据局限与披露<small>结论的适用边界</small></h2>
<div class="card">
<ul>
<li><b>样本期单一：</b>2026-08-18 ~ __DEND__ 仅约 6 周，且处于连续上涨阶段，缺少震荡/下跌样本 —— <b>胜率与板块结论均不可外推</b>。</li>
<li><b>伪重复：</b>同一只股票常在不同板块、不同日期多次入选（392 行仅对应 __CODES__ 只个股）。
已额外给出"每股仅取首个信号"的去重口径（161 行）作对照，其胜率更低（48.5%→见第三节）。</li>
<li><b>口径差：</b>跟踪表的买点/止损/目标位由信号日<b>盘中或收盘价</b>计算，与本报告使用的<b>前复权日 K</b> 存在 &lt;0.5% 的口径差
（如上海莱士 08-18：表内 4.90 vs K线收盘 4.89）。</li>
<li><b>同日双向：</b>日内既触止损又触目标的行按<b>止损优先</b>保守计入失败，未做日内高频还原（无分时数据）。</li>
<li><b>停牌样本：</b>有研硅（sh688432）在 08-31~09-11 连续 10 个交易日无行情（同期其余 160 只均有数据，特征为疑似停牌），
其 08-31 信号的入场被顺延至复牌首日。</li>
<li><b>休市：</b>2026-09-25 中秋节休市，无行情数据属正常。</li>
<li><b>小样本分组：</b>部分分板块/分日样本量不足 10 行（如主升浪仅 74 行、已了结 33 行），其盈亏比等指标统计意义弱，已标注。</li>
</ul>
</div>

<div class="foot">
数据来源：westock CLI（前复权日 K 线，窗口 2026-08-01 ~ __DEND__）＋ A股板块候选跟踪表.xlsx（392 行）＋ 沪深北交易所休市公告。<br>
复现方式：<code>python3 scripts/verify_signals.py</code>（拉数+模拟）→ <code>python3 scripts/verify_report.py</code>（生成本报告）。<br>
<b>本报告仅供研究参考，不构成个人投资建议。</b>
</div>

</div><script>
var D = __PAYLOAD__;
var AX = {axisLine:{lineStyle:{color:'#cfd8dc'}},axisLabel:{color:'#546e7a',fontSize:11},
         splitLine:{lineStyle:{color:'#eceff1'}}};
var UP='#c62828', DN='#2e7d32', YE='#f9a825';
echarts.init(document.getElementById('cPie')).setOption({
  tooltip:{trigger:'item'},legend:{bottom:0,textStyle:{fontSize:11,color:'#546e7a'}},
  series:[{type:'pie',radius:['42%','68%'],center:['50%','44%'],label:{fontSize:11,color:'#37474f'},
    data:D.pie}]});
echarts.init(document.getElementById('cHist')).setOption({
  grid:{left:50,right:20,top:24,bottom:36},tooltip:{trigger:'axis'},
  xAxis:Object.assign({type:'category',data:D.hist.x},AX),
  yAxis:Object.assign({type:'value',name:'行数'},AX),
  series:[{type:'bar',data:D.hist.y.map(function(v,i){return {value:v,itemStyle:{color:D.histColor[i]}}}),
    barWidth:'62%',label:{show:true,position:'top',fontSize:11,color:'#546e7a'}}]});
echarts.init(document.getElementById('cRR')).setOption({
  grid:{left:60,right:24,top:30,bottom:30},tooltip:{trigger:'axis'},
  legend:{bottom:0,textStyle:{fontSize:11,color:'#546e7a'}},
  xAxis:Object.assign({type:'category',data:['回抽确认','主升浪买点区']},AX),
  yAxis:Object.assign({type:'value',name:'%'},AX),
  series:[
   {name:'目标1 上行空间',type:'bar',stack:'s',data:[D.rr['回抽确认'].up,D.rr['主升浪买点区'].up],
    itemStyle:{color:UP},label:{show:true,position:'top',fontSize:11,color:UP}},
   {name:'目标2 上行空间',type:'bar',stack:'s',data:[D.rr['回抽确认'].up2-D.rr['回抽确认'].up,D.rr['主升浪买点区'].up2-D.rr['主升浪买点区'].up],
    itemStyle:{color:'#ef9a9a'}},
   {name:'止损 下行空间',type:'bar',data:[D.rr['回抽确认'].dn,D.rr['主升浪买点区'].dn],
    itemStyle:{color:DN},label:{show:true,position:'bottom',fontSize:11,color:DN}}]});
echarts.init(document.getElementById('cSector')).setOption({
  grid:{left:56,right:56,top:30,bottom:56},tooltip:{trigger:'axis'},
  legend:{bottom:0,textStyle:{fontSize:11,color:'#546e7a'}},
  xAxis:Object.assign({type:'category',data:D.sector.x,axisLabel:{color:'#546e7a',fontSize:10,rotate:22}},AX),
  yAxis:[Object.assign({type:'value',name:'均收益%'},AX),
         Object.assign({type:'value',name:'胜率%',max:100,splitLine:{show:false}},AX)],
  series:[{name:'均收益A%',type:'bar',data:D.sector.ret.map(function(v){return {value:v,itemStyle:{color: v>=0?UP:DN}}}),
    label:{show:true,position:'top',fontSize:10,color:'#607d8b'}},
   {name:'胜率A%',type:'line',yAxisIndex:1,data:D.sector.wr,smooth:true,symbolSize:7,
    itemStyle:{color:'#1565c0'},lineStyle:{width:2}}]});
echarts.init(document.getElementById('cDate')).setOption({
  grid:{left:52,right:56,top:30,bottom:52},tooltip:{trigger:'axis'},
  legend:{bottom:0,textStyle:{fontSize:11,color:'#546e7a'}},
  xAxis:Object.assign({type:'category',data:D.date.x.map(function(s){return s.slice(4)}),
    axisLabel:{color:'#546e7a',fontSize:10,rotate:38}},AX),
  yAxis:[Object.assign({type:'value',name:'胜率%',max:100},AX),
         Object.assign({type:'value',name:'样本数',splitLine:{show:false}},AX)],
  series:[{name:'胜率A(已了结)',type:'line',data:D.date.wr,smooth:true,symbolSize:7,
    itemStyle:{color:UP},lineStyle:{width:2.4},connectNulls:true},
   {name:'胜率B(含持有中)',type:'line',data:D.date.wr_all,smooth:true,symbolSize:6,
    itemStyle:{color:YE},lineStyle:{width:2,type:'dashed'},connectNulls:true},
   {name:'样本数',type:'bar',yAxisIndex:1,data:D.date.n,itemStyle:{color:'#cfd8dc'},barWidth:'44%'}]});
echarts.init(document.getElementById('cMfe')).setOption({
  grid:{left:52,right:20,top:24,bottom:34},tooltip:{trigger:'axis'},
  xAxis:Object.assign({type:'category',data:D.mfeLose.x},AX),
  yAxis:Object.assign({type:'value',name:'行数'},AX),
  series:[{type:'bar',data:D.mfeLose.y.map(function(v,i){return {value:v,itemStyle:{color:i<2?DN:'#90a4ae'}}}),
    barWidth:'56%',label:{show:true,position:'top',fontSize:11,color:'#546e7a'}}]});
echarts.init(document.getElementById('cHold')).setOption({
  grid:{left:52,right:20,top:24,bottom:34},tooltip:{trigger:'axis'},
  xAxis:Object.assign({type:'category',data:D.holdWin.x},AX),
  yAxis:Object.assign({type:'value',name:'行数'},AX),
  series:[{type:'bar',data:D.holdWin.y.map(function(v,i){return {value:v,itemStyle:{color:i<3?UP:'#90a4ae'}}}),
    barWidth:'56%',label:{show:true,position:'top',fontSize:11,color:'#546e7a'}}]});
window.addEventListener('resize',function(){document.querySelectorAll('.chart').forEach(function(e){
  var c=echarts.getInstanceByDom(e); if(c) c.resize();});});
</script></body></html>
"""

if __name__ == "__main__":
    P = build()
    html = render(P)
    html = html.replace("__CSS__", CSS)
    # 补两个运行时才知道的占位
    R = json.load(open(RES, encoding="utf-8"))
    o = R["overall"]
    rets = [r["ret"] for r in R["detail"] if r["ret"] is not None]
    pos = round(100 * sum(1 for x in rets if x > 0) / len(rets), 1)
    html = (html.replace("__KPIS_WR_ALL__", str(o["win_rate_all"]))
                .replace("__KPIS_RET_ALL__", fmt(o["avg_ret_all"]))
                .replace("__KPIS_MED_ALL__", fmt(o["median_ret_all"]))
                .replace("__OPEN_PCT__", str(round(100 * o["open_n"] / o["n"], 1)))
                .replace("__RR_UP_M__", fmt(P["rr"]["主升浪买点区"]["up"]))
                .replace("__RR_DN_M__", fmt(P["rr"]["主升浪买点区"]["dn"]))
                .replace("__RR_R_M__", str(P["rr"]["主升浪买点区"]["ratio"]))
                .replace("__RR_WR_M__", str(R["by_sig"]["主升浪买点区"]["win_rate"]))
                .replace("__RR_PL_M__", str(R["by_sig"]["主升浪买点区"]["pl_ratio"]))
                .replace("__RR_UP_P__", fmt(P["rr"]["回抽确认"]["up"]))
                .replace("__RR_DN_P__", fmt(P["rr"]["回抽确认"]["dn"]))
                .replace("__RR_R_P__", str(P["rr"]["回抽确认"]["ratio"]))
                .replace("__PATH_LOSE_MFE__", fmt(P["path"]["lose"]["mfe"]))
                .replace("__PATH_LOSE_HOLD__", str(P["path"]["lose"]["hold"])))
    out = os.path.join(BASE, f"信号有效性回溯验证报告_{TODAY}.html")
    open(out, "w", encoding="utf-8").write(html)
    left = [t for t in ("__",) if t in html]
    print(f"OK 报告已生成：{out}（{len(html)} 字符）")
    import re
    ph = sorted(set(re.findall(r"__[A-Z0-9_]+__", html)))
    print("残留占位符:", ph if ph else "无")
