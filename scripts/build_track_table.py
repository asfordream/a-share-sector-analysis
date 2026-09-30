#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Step H：A股板块 🔴 候选跟踪表（本地 Excel **滚动表**，2026-08-18 用户拍板设计）。

口径（跟踪表专用，比 Step G 自选股更宽；裁决由 tech4.compute 实时算）：
- 入选板块 = 裁决 emoji==🔴 ∪ 格局含「反弹可参与」∪「结构已立」∪「加码・匹配执行」
  （2026-08-18 首次扩展；2026-08-19 用户追加「加码・匹配执行」。
   持有・匹配执行 / 观察・匹配执行 不入选；Step G 写自选股仍只收 🔴 板块。）
- 取每板块 cands(回抽确认) + mups(主升浪买点区)，按 code 去重（同股双信号各一行）
- ⚠️ 2026-08-27 用户拍板：仅「确认态==已确认」的候选记入（待确认不入表）

输出结构（2026-09-29 用户需求：跟踪表拆为两张表）：
同一个 xlsx 内两个 sheet ——「回抽确认」(cands) / 「主升浪买点区」(mups)，各自独立滚动、
独立幂等；历史单 sheet「🔴候选跟踪」在首次运行时按「信号类型」列自动分流迁移。
（若要改成两个独立文件，只需把 XLSX 派生两个路径，本脚本其余逻辑不用动。）

行字段（21 列）：
日期 | 板块 | 板块形态 | 信号类型 | 个股代码 | 个股名称 | 信号日现价 | 信号日距MA20% |
持有周期 | 建议仓位 | 买点区间 | 止损线 | 目标1(MA60) | 目标2(前高+20%) |
52周前高 | 前高位置% | 当前状态 | 曾达档位 | 首破位日 | 状态变更日 | 确认态

═══ 2026-09-29 三处用户拍板的改动 ═══

【A4 已落】第 16 列由「空间% = 目标2/买点上限-1」改为「前高位置% = 现价 ÷ 52周前高 × 100」。
  原口径方向反直觉：85% 的回抽行恒等于 +20.0%（默认 ×1.2 封顶），且 >+20% 反而是 MA60 远在上方
  的深跌结构 —— 「越大越差」，与收益负相关（r=-0.127）；换后单调「越大越强」。

【E 目标阶梯 6 档】状态从「相对买点区的处境」改为「这波走到目标链的哪一格」，且**每日刷新、可升可降**：
  已破位(≤止损线) > 52周高位(≥52前高×0.95) > 逼近前高(≥52前高×0.85)
  > 第一目标(≥目标1) > 上涨中(买点下限≤现价<目标1) > 回调中(止损线<现价<买点下限)
  配套三列：**当前状态**（天天变，答"今天在哪"）、**曾达档位**（只升不降，答"曾经到过哪"，
  实测 74.7% 的行会因缺此列而丢失"曾经更强过"）、**首破位日**（首次破位写一次，答"何时出过局"）。
  ⚠️ 原「状态」列的终态锁定（已止损/已止盈写死）**已删除** —— 那正是"表看起来不更新"的根源。

【F 滚动覆盖 + 归档】去重键由（日期,板块,code,信号类型）改为 **(板块, code)**：同一板块下同一只股
  只保留**最新一次信号**那一行，旧行移入隐藏 sheet「已归档」（**不是删除** —— 否则
  verify_signals.py 直接失去样本、回溯结论不可复现）。实测 392 → 217 行，归档 175 行。
  ⚠️ 必须含「板块」：同 sheet 内有 34(回抽)/7(主升) 只股跨板块重复，只按 code 会吞掉 41 个板块归属。
  ⚠️ 覆盖时**继承**旧行的「曾达档位」「首破位日」（不可逆事实不该因换了个信号日被清零）。

价位规则（universe 字段 price/ma20/ma60/hi52/rsi6/distMa20）：
- 持有周期：回抽确认→"短线 1~2 周"；主升浪→"波段 2~4 周"（2026-09-29 A1：改为与实测持有期一致）
- 建议仓位：回抽确认→"标准仓 50%（两批）"、主升浪→"半仓 30~50%"；RSI6≥70 超买→"轻仓 25%（超买）"
- 买点区间：回抽确认=[ma20*0.97, ma20]（回踩MA20 -3%~0%）；主升浪=[ma20*0.85, ma20*1.05]
- 止损线 = min(ma20, 买点下限*0.92)（破MA20 或 买点-8% 取更严），输出数值+「破MA20离场」
- 目标1 = MA60（若 ma60≤现价 则 现价*1.10 兜底）→ 状态档位名用「第一目标」而非「MA60」，
  因为实测 32.7% 的行目标1 实为 现价*1.10，叫 MA60 会误导。

用法：python3 scripts/build_track_table.py   （Python 用带 openpyxl 的 envs/default）
输出：工作区根目录 A股板块候选跟踪表.xlsx
⚠️ 落改前先确认 data/_summary.json 的 mtime 是当日 —— rd 取当日日期，若 summary 过期会造出假行。
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tech4  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
XLSX = os.path.join(BASE, "A股板块候选跟踪表.xlsx")
HEADERS = ["日期", "板块", "板块形态", "信号类型", "个股代码", "个股名称",
           "信号日现价", "信号日距MA20%",
           "持有周期", "建议仓位", "买点区间", "止损线", "目标1(MA60)", "目标2(前高+20%)",
           "52周前高", "前高位置%",
           "当前状态", "曾达档位", "首破位日", "状态变更日", "确认态"]

# 列号常量（1-based；改列序时必须同步这里 + HEADERS + COL_WIDTHS + _row 的返回顺序）
C_DATE, C_SECTOR, C_CODE, C_SIG = 1, 2, 5, 4
C_PRICE, C_BUY, C_STOP, C_T1, C_HI52, C_POS52 = 7, 11, 12, 13, 15, 16
C_STATE, C_PEAK, C_FBREAK, C_CHANGED, C_CONFIRM = 17, 18, 19, 20, 21

# 2026-09-29 用户需求：跟踪表拆为两张表 —— 同一 xlsx 内两个 sheet，按信号类型分流
SHEET_ORDER = ["回抽确认", "主升浪买点区"]
LEGACY_SHEET = "🔴候选跟踪"
ARCHIVE_SHEET = "已归档"
ARCH_HEADERS = HEADERS + ["归档日", "归档时状态"]
COL_WIDTHS = [10, 12, 16, 10, 12, 10, 11, 13, 12, 16, 16, 16, 12, 14, 10, 9, 10, 10, 11, 11, 10]
ARCH_WIDTHS = COL_WIDTHS + [10, 10]

# ── E 目标阶梯 ──────────────────────────────────────────────────────────────
# 强弱序（由弱到强）。「已破位」是并列的**终态**，不进这个序列：
# 它在判定上最优先，但语义上是"出局"，所以「曾达档位」只取本序列的 max，
# "何时出过局"由独立的「首破位日」列承载。
TIER_ORDER = ["回调中", "上涨中", "第一目标", "逼近前高", "52周高位"]
NEAR_HIGH = 0.85   # 「逼近前高」：距 52 周前高 15% 以内（实测命中 25 行）
TOP_HIGH = 0.95    # 「52周高位」：距前高 5% 以内或已创新高（实测命中 17 行）
BREAK_STATE = "已破位"
# 「当前状态」的合法词表：阶梯 5 档 + 终态「已破位」
VALID_STATES = set(TIER_ORDER) | {BREAK_STATE}
# 旧「状态」列里**唯一可靠的历史事实**：已止盈 = 曾 ≥ 目标1（旧代码 target1 是纯数字，
# 未被 num() bug 污染；已止损则因该 bug 恒写不出，392 行 0 例）。
# 迁移时用它给「曾达档位」播种 → 否则今日已破位/回调中的行会丢失"曾经到过第一目标"。
# 「已触发/待触发」语义含糊（可能是回调中也可能上涨中）→ **不播种**，宁可留空不臆测。
LEGACY_PEAK = {"已止盈": "第一目标"}


def _write_row(ws, values):
    """显式按 max_row+1 写入一行。

    ⚠️ 不用 ws.append()：openpyxl 的 append 依据内部 _current_row 游标，而读取空 sheet 的
    ws.cell(1,1) 会把该游标推到第 1 行 → 表头被写到第 2 行、重跑还会重复插表头（2026-09-29 踩坑）。
    显式行号写入彻底绕开该行为。
    """
    r = ws.max_row + 1
    if ws.cell(1, 1).value in (None, ""):
        r = 1  # 完全空表（连表头都没有）→ 从第 1 行起
    for i, v in enumerate(values, 1):
        ws.cell(r, i).value = v
    return r


def _ensure_header(ws):
    """保证第 1 行为完整表头；旧文件缺列时补列，列名变更时同步。

    2026-09-29：第 16 列「空间%」→「前高位置%」，存量表头需随之改写，
    否则列名与列内数据口径不一致（旧分支只补列、不改已存在的列名）。
    """
    if ws.cell(1, 1).value in (None, ""):
        for i, h in enumerate(HEADERS, 1):
            ws.cell(1, i).value = h
        return
    for i, h in enumerate(HEADERS, 1):
        cur = ws.cell(1, i).value
        if cur in (None, ""):
            ws.cell(1, i).value = h  # 缺列 → 补
        elif str(cur) != h:
            print(f"    表头同步：第 {i} 列「{cur}」→「{h}」")
            ws.cell(1, i).value = h


def _migrate_columns(ws):
    """把存量的 18 列结构就地升级到 21 列（2026-09-29）。

    ⚠️ 关键：新列插在原第 17 列「状态」之后，所以原第 18 列「确认态」必须**整体后移到第 21 列**，
    否则会被当成新的「曾达档位」列，出现"曾达档位 = 已确认"这种脏数据。
    必须在 _ensure_header 之前调用（后者的列名同步只改名、不搬数据）。
    顺带：按 LEGACY_PEAK 把旧状态里的可靠历史事实播种进「曾达档位」。
    返回移动的行数；已是新结构则返回 0。
    """
    if ws.cell(1, 1).value in (None, ""):
        return 0
    if str(ws.cell(1, C_CONFIRM).value or "") == HEADERS[C_CONFIRM - 1]:
        return 0  # 已是新结构（第 21 列已是「确认态」）
    moved = 0
    for r in range(2, ws.max_row + 1):
        v = ws.cell(r, C_PEAK).value          # 旧「确认态」在第 18 列（= 新的「曾达档位」位）
        if v not in (None, ""):
            moved += 1
        seed = LEGACY_PEAK.get(ws.cell(r, C_STATE).value, "")   # 旧状态 → 曾达档位种子
        for c in (C_PEAK, C_FBREAK, C_CHANGED):
            ws.cell(r, c).value = None        # 清掉 18/19/20 列，避免残留脏值
        ws.cell(r, C_PEAK).value = seed       # 曾达档位（当前状态由 main 步骤 1 重算）
        ws.cell(r, C_CONFIRM).value = v       # 确认态后移到第 21 列
    return moved


def _backfill_pos52(ws):
    """重算第 16 列「前高位置%」= 现价 ÷ 52周前高 × 100（越大越强）。返回改动行数。

    2026-09-29 该列由「空间%」改名重算。历史行的「现价」(第 7 列) 与「52周前高」(第 15 列)
    都是信号日冻结值、不会被后续 run 改写，故重算可复现、重跑幂等（第二次跑改动 0 行）。
    任一分量为空（n/a）→ 保持 n/a，不臆测。
    """
    n = 0
    for r in range(2, ws.max_row + 1):
        p = num(ws.cell(r, C_PRICE).value)
        hi52 = num(ws.cell(r, C_HI52).value)
        new = f"{p / hi52 * 100:.1f}%" if (p and hi52) else "n/a"
        if ws.cell(r, C_POS52).value != new:
            ws.cell(r, C_POS52).value = new
            n += 1
    return n


def _style(ws, widths=None):
    """表头加粗 + 自适应列宽 + 自动筛选。"""
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter
    for c in ws[1]:
        c.font = Font(bold=True)
    ws.auto_filter.ref = ws.dimensions
    for i, w in enumerate(widths or COL_WIDTHS, 1):
        ws.column_dimensions[get_column_letter(i)].width = w


def _ensure_archive(wb):
    """确保隐藏 sheet「已归档」存在并返回它。

    F2：被滚动覆盖掉的旧行**移到这里，不是删除** —— 否则 verify_signals.py 直接失去样本、
    回溯结论不可复现，也违背"绝不删改历史"的既有铁律。
    结构 = 主表 21 列 + 「归档日」「归档时状态」。
    """
    if ARCHIVE_SHEET not in wb.sheetnames:
        ws = wb.create_sheet(ARCHIVE_SHEET)
        for i, h in enumerate(ARCH_HEADERS, 1):
            ws.cell(1, i).value = h
        ws.sheet_state = "hidden"
    return wb[ARCHIVE_SHEET]


def _migrate_legacy(wb):
    """把旧的单 sheet「🔴候选跟踪」按信号类型拆分为两个 sheet（仅首次运行生效）。

    返回：None = 无旧 sheet 无需迁移；int = 已迁移，值为此处无法识别信号类型的行数
    （>0 时旧 sheet 改名「其他(待核对)」保留，绝不静默丢数据）。
    """
    if LEGACY_SHEET not in wb.sheetnames:
        return None
    if all(n in wb.sheetnames for n in SHEET_ORDER):
        return None  # 已是拆分后的结构，不动
    legacy = wb[LEGACY_SHEET]
    buckets = {n: [] for n in SHEET_ORDER}
    unknown = []
    for r in range(2, legacy.max_row + 1):
        vals = [legacy.cell(r, c).value for c in range(1, legacy.max_column + 1)]
        if not any(v not in (None, "") for v in vals):
            continue
        sig = str(legacy.cell(r, 4).value or "")
        (buckets[sig] if sig in buckets else unknown).append(vals)
    for name in SHEET_ORDER:
        ws = wb.create_sheet(name)
        _ensure_header(ws)
        for vals in buckets[name]:
            _write_row(ws, (list(vals) + [None] * len(HEADERS))[:len(HEADERS)])
        _style(ws)
    if unknown:
        legacy.title = "其他(待核对)"
    else:
        wb.remove(legacy)
    return len(unknown)


def num(v):
    """从 `4.51（破MA20离场）` / `n/a` / `3.2` 中取出前导数字。

    ⚠️ 2026-09-29 修（原 E5/C1）：旧实现是裸 `float(v)`，而「止损线」单元格带中文后缀 →
    解析恒为 None → **「已破位」永远写不出来**（392 行 0 例，实际有 76 行已跌破止损线）。
    改为正则取前导数字；其余调用点传入的都是纯数字，行为不变。
    """
    if v is None:
        return None
    m = re.match(r"\s*([+-]?\d+(?:\.\d+)?)", str(v))
    return float(m.group(1)) if m else None


def norm_code(code):
    """去掉交易所标志：sz/sh/bj 前缀 → 纯数字代码。"""
    code = (code or "").strip()
    for p in ("sz", "sh", "bj"):
        if code[:2].lower() == p:
            return code[2:]
    return code


def _tier(price, lo, stop, t1, hi52):
    """目标阶梯 6 档判定（2026-09-29 用户定向）。取不到价返回 None。

    判定序：已破位 > 52周高位 > 逼近前高 > 第一目标 > 上涨中 > 回调中。
    ⚠️ 「已破位」置顶是为了让"出局"这个事实优先于一切 —— 判定序 ≠ 强弱序。
    实测：`现价<买点下限 且 现价≥目标1` 的行 = 0/392，所以判定顺序不影响结果。
    """
    if price is None:
        return None
    if stop is not None and price <= stop:
        return BREAK_STATE
    if hi52 and price >= hi52 * TOP_HIGH:
        return "52周高位"
    if hi52 and price >= hi52 * NEAR_HIGH:
        return "逼近前高"
    if t1 is not None and price >= t1:
        return "第一目标"
    if lo is not None and price >= lo:
        return "上涨中"
    return "回调中"


def _row(rd, sector, shape, sig, c, x, confirm="—"):
    code = norm_code(c.get("code"))
    name = c.get("name") or x.get("name") or ""
    price = num(x.get("price"))
    ma20 = num(x.get("ma20"))
    ma60 = num(x.get("ma60"))
    rsi6 = num(x.get("rsi6"))
    hi52 = num(x.get("hi52"))
    dm = num(c.get("distMa20"))
    if dm is None:
        dm = num(x.get("distMa20"))
    dm_s = f"{dm:+.2f}%" if dm is not None else "n/a"

    # 持有周期 / 仓位（2026-09-29 A1：标签改为与实测持有期一致；
    # 实测回抽中位持有 6 日、主升中位 6 日，旧的「波段2~4周 / 中线1~3月」严重高估）
    if sig == "回抽确认":
        period, pos = "短线 1~2 周", "标准仓 50%（两批）"
    else:
        period, pos = "波段 2~4 周", "半仓 30~50%"
    if rsi6 is not None and rsi6 >= 70:
        pos += "；超买减半"

    # 买点区间 / 止损 / 目标
    lo = stop = t1 = None
    if price and ma20:
        lo, hi = (ma20 * 0.97, ma20) if sig == "回抽确认" else (ma20 * 0.85, ma20 * 1.05)
        if price < lo:
            lo = price  # 已破买点下限 → 区间从现价起
        buy = f"{lo:.2f}~{hi:.2f}"
        stop = min(ma20, lo * 0.92)
        stop_s = f"{stop:.2f}（破MA20离场）"
        t1 = ma60 if (ma60 and ma60 > price) else price * 1.10
        t1_s = f"{t1:.2f}"
        hi52_s = f"{hi52:.2f}" if hi52 else "n/a"
        t2 = min(hi52, hi * 1.20) if hi52 else hi * 1.20
        t2 = max(t2, t1)  # 目标2 不低于目标1
        t2_s = f"{t2:.2f}"
        # 前高位置% = 现价 ÷ 52周前高 × 100（越大越强；2026-09-29 替换原「空间%」）
        pos52_s = f"{price / hi52 * 100:.1f}%" if hi52 else "n/a"
    else:
        hi52 = None
        buy = stop_s = t1_s = t2_s = hi52_s = pos52_s = "n/a"

    # 初始状态：与次日重算共用 _tier，保证"新行"和"次日重算"口径一致
    # （旧实现是写死「待触发」再在写入时改成「已触发」，与新状态机是两套口径）
    st = _tier(price, lo, stop, t1, hi52) or "回调中"
    peak = st if st in TIER_ORDER else ""
    fbreak = rd if st == BREAK_STATE else ""
    return [rd, sector, shape, sig, code, name,
            f"{price:.2f}" if price else "n/a", dm_s,
            period, pos, buy, stop_s, t1_s, t2_s, hi52_s, pos52_s,
            st, peak, fbreak, rd, confirm]


def _status(cur, peak, fbreak, changed, today,
            price, buy_cell, stop_cell, tgt_cell, hi52_cell):
    """按当日现价重算状态（2026-09-29 起**每日刷新、可升可降**）。

    返回 (当前状态, 曾达档位, 首破位日, 状态变更日)。三列分工：
    - 当前状态   ：纯当日快照，可升可降  —— 答"今天在哪"
    - 曾达档位   ：阶梯 max，只升不降    —— 答"曾经到过哪"
    - 首破位日   ：首次破位写一次，不改写 —— 答"何时出过局"
    - 状态变更日 ：状态一旦变化即刷新为当日；迁移时若状态未变则留空（= 变更日未知，不臆测）

    ⚠️ 2026-09-29 删除了旧的终态永久锁定（`if cur in ("已止损","已止盈"): return cur`）
    —— 那正是"表看起来不更新"的根源；不可逆事实改由「曾达档位」「首破位日」留痕。

    ⚠️ 取不到现价时（个股掉出当日 universe）当前状态**留空**而不是保留旧词：旧的
    「已止盈/已触发/待触发」已不是新阶梯的合法档位名，原样留着会在表里显出过期词汇。
    留空 = "本轮无价、未刷新"，信息不臆测（旧值可从 `_backup/A股板块候选跟踪表_EF改前_20260929.xlsx` 追溯）。
    """
    peak = peak if peak in TIER_ORDER else ""
    fbreak = fbreak or ""
    changed = changed or ""
    if price is None:
        # 无现价 → 无法判定；只保留仍合法的档位名，旧词表（已止盈/已触发/待触发）留空
        return (cur if cur in VALID_STATES else "", peak, fbreak, changed)
    try:
        lo = float(str(buy_cell).split("~")[0])
    except Exception:
        lo = None
    st = _tier(price, lo, num(stop_cell), num(tgt_cell), num(hi52_cell)) or "回调中"
    if st in TIER_ORDER and (not peak or TIER_ORDER.index(st) > TIER_ORDER.index(peak)):
        peak = st
    if st == BREAK_STATE and not fbreak:
        fbreak = today
    if st != (cur or ""):
        changed = today
    return (st, peak, fbreak, changed)


def main():
    S = json.load(open(os.path.join(DATA, "_summary.json"), encoding="utf-8"))
    rd = datetime_now()
    rows, universe_price = [], {}
    for s in S:
        d = json.load(open(os.path.join(DATA, f"{s['name']}.json"), encoding="utf-8"))
        for x in d.get("universe") or []:
            code = norm_code(x.get("code"))
            p = num(x.get("price"))
            if code and p:
                universe_price[code] = p
    for s in S:
        U, sq = tech4.load_universe(DATA, s["name"])
        t4 = tech4.compute(U, sq, s.get("rating"))
        if not t4:
            continue
        vt = t4["verdict_type"]
        # 入选口径（2026-08-18 用户扩展 + 2026-08-19 追加「加码・匹配执行」）：
        #   🔴 裁决 ∪ 「反弹可参与」∪「结构已立」∪「加码・匹配执行」
        # 注：仅 加码 组的匹配执行入选（评级进攻+技术面同向匹配，属可执行档）；
        #     持有・匹配执行 / 观察・匹配执行 不入选。Step G 自选股仍只收 🔴。
        in_scope = ((t4["conclusion_emo"] == "🔴")
                    or ("反弹可参与" in vt) or ("结构已立" in vt)
                    or (vt.startswith("加码") and "匹配执行" in vt))
        if not in_scope:
            continue
        by_code = {norm_code(x.get("code")): x for x in U}
        shape = t4["verdict_type"]
        for sig, lst in (("回抽确认", s.get("cands")), ("主升浪买点区", s.get("mups"))):
            for c in lst or []:
                confirm = c.get("confirm") or "—"
                # 仅「已确认」候选记入跟踪表（2026-08-27 用户拍板：确认态作为写入门槛）
                if confirm != "已确认":
                    continue
                rows.append(_row(rd, s["name"], shape, sig, c,
                                 by_code.get(norm_code(c.get("code"))) or {}, confirm=confirm))

    from openpyxl import Workbook, load_workbook
    if os.path.exists(XLSX):
        wb = load_workbook(XLSX)
        unknown = _migrate_legacy(wb)
        if unknown is not None:
            print(f"  迁移：旧单 sheet「{LEGACY_SHEET}」已按信号类型拆分为 "
                  f"{' / '.join(SHEET_ORDER)}"
                  + (f"；{unknown} 行信号类型无法识别 → 留在「其他(待核对)」" if unknown else ""))
    else:
        wb = Workbook()
        wb.remove(wb.active)  # 不用默认空表，按 SHEET_ORDER 建

    # 确保目标 sheet 存在 + 列结构升级到 21 列 + 表头完整
    # 先按「信号类型」分流，再统一建表：SHEET_ORDER ∪ 出现的信号类型（兜底未知类型不丢行）
    rows_by_sig = {n: [] for n in SHEET_ORDER}
    for row in rows:
        rows_by_sig.setdefault(row[3], []).append(row)
    for name in rows_by_sig:
        if name not in wb.sheetnames:
            wb.create_sheet(name)
        moved = _migrate_columns(wb[name])   # ⚠️ 必须在 _ensure_header 之前
        if moved:
            print(f"  [{name}] 列结构升级 18→21：「确认态」后移 {moved} 行到第 21 列")
        _ensure_header(wb[name])

    arch = _ensure_archive(wb)
    arch_total = 0
    added_total = 0
    stat_lines = []
    for name, lst in rows_by_sig.items():
        ws = wb[name]
        # 0) 重算「前高位置%」（第 16 列；2026-09-29 由「空间%」改名重算，可复现、幂等）
        recalced = _backfill_pos52(ws)
        # 1) 更新历史行：当前状态 / 曾达档位 / 首破位日 / 状态变更日（2026-09-29 起可升可降）
        noprice = 0
        for r in range(2, ws.max_row + 1):
            raw = ws.cell(r, C_CODE).value
            code = norm_code(raw) if raw else ""
            if raw != code:
                ws.cell(r, C_CODE).value = code  # 规范化历史行交易所标志
            p = universe_price.get(code) if code else None
            if p is None:
                noprice += 1  # 掉出当日 universe → 状态留空，不做"沿用旧值"的臆测
            vals = _status(ws.cell(r, C_STATE).value, ws.cell(r, C_PEAK).value,
                           ws.cell(r, C_FBREAK).value, ws.cell(r, C_CHANGED).value, rd,
                           p, ws.cell(r, C_BUY).value, ws.cell(r, C_STOP).value,
                           ws.cell(r, C_T1).value, ws.cell(r, C_HI52).value)
            for col, val in ((C_STATE, vals[0]), (C_PEAK, vals[1]),
                             (C_FBREAK, vals[2]), (C_CHANGED, vals[3])):
                if ws.cell(r, col).value != val:
                    ws.cell(r, col).value = val
        # 2) 滚动：新行 (板块,code) 命中的旧行 → 移入「已归档」并从本表删除；
        #    同时把旧行的不可逆战绩（曾达档位 / 首破位日）留给新行继承（F5）。
        newkeys = {(row[C_SECTOR - 1], row[C_CODE - 1]) for row in lst}
        inherit, trims = {}, []
        for r in range(2, ws.max_row + 1):
            k = (str(ws.cell(r, C_SECTOR).value or ""), norm_code(ws.cell(r, C_CODE).value))
            if k not in newkeys:
                continue
            if str(ws.cell(r, C_DATE).value or "") == rd:
                continue  # 同日行不归档（重跑幂等，否则会反复归档）
            inherit[k] = (ws.cell(r, C_PEAK).value or "", ws.cell(r, C_FBREAK).value or "")
            trims.append(r)
        archived = 0
        for r in reversed(trims):  # ⚠️ delete_rows 必须从后往前，正序删会因索引位移漏删
            vals = [ws.cell(r, c).value for c in range(1, len(HEADERS) + 1)]
            _write_row(arch, list(vals) + [rd, vals[C_STATE - 1]])
            ws.delete_rows(r, 1)
            archived += 1
        # 3) 幂等追加当日新行
        existing = set()
        for r in range(2, ws.max_row + 1):
            existing.add((str(ws.cell(r, C_DATE).value or ""), str(ws.cell(r, C_SECTOR).value or ""),
                          norm_code(ws.cell(r, C_CODE).value), str(ws.cell(r, C_SIG).value or "")))
        added = 0
        for row in lst:
            key = (row[C_DATE - 1], row[C_SECTOR - 1], row[C_CODE - 1], row[C_SIG - 1])
            if key in existing:
                continue  # 当日该板块已追加过（重跑幂等）
            existing.add(key)  # 同 run 内也要防重
            inh = inherit.get((row[C_SECTOR - 1], row[C_CODE - 1]))
            if inh:
                old_pk, old_fb = inh
                if old_pk in TIER_ORDER and (row[C_PEAK - 1] not in TIER_ORDER
                                             or TIER_ORDER.index(old_pk) > TIER_ORDER.index(row[C_PEAK - 1])):
                    row[C_PEAK - 1] = old_pk
                    # 曾达被抬到更高档 → 当前状态若仍更低，说明是"曾经更强"，不动当前状态
                if old_fb and not row[C_FBREAK - 1]:
                    row[C_FBREAK - 1] = old_fb
            _write_row(ws, row)
            added += 1
        added_total += added
        arch_total += archived
        _style(ws)
        stat_lines.append(f"  [{name}] 当日候选 {len(lst)} 行 → 新增 {added} 行"
                          f"（幂等跳过 {len(lst) - added} 行）；滚动归档 {archived} 行"
                          f"；表内现有 {ws.max_row - 1} 行（前高位置% 重算 {recalced} 行"
                          f"，无价未刷新 {noprice} 行）")
    if arch_total:
        _style(arch, ARCH_WIDTHS)
    wb.save(XLSX)
    print(f"OK 跟踪表已更新（滚动表 {' / '.join(SHEET_ORDER)} + 隐藏「{ARCHIVE_SHEET}」）: {XLSX}")
    print(f"  当日候选 {len(rows)} 行 → 实际新增 {added_total} 行"
          f"（重跑幂等跳过 {len(rows) - added_total} 行）；滚动归档 {arch_total} 行"
          f"；入选板块: {sorted(set(r[C_SECTOR - 1] for r in rows))}")
    for line in stat_lines:
        print(line)
    for r in rows:
        print(f"    {r[0]} {r[1]} [{r[3]}] {r[4]} {r[5]} 买点{r[10]} 止损{r[11]} 目标{r[12]}")


def datetime_now():
    from datetime import datetime
    return os.environ.get("REPORT_DATE") or datetime.now().strftime("%Y%m%d")


if __name__ == "__main__":
    main()
