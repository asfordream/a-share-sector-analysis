# -*- coding: utf-8 -*-
"""
early_screen.py — 十五五潜力股「早筛清单」生成器 (L2/L4)
=======================================================
用法:
    python3 scripts/early_screen.py            # 生成本地 HTML 早筛报告
    python3 scripts/early_screen.py --sectors 机器人,算力   # 仅指定赛道

设计 (对齐 十五五潜力股选股方法论.md):
    L1 政策主线  -> 写死在 SECTORS_15_5
    L2 新晋卡位/转型扫描 -> 本报告给「方法 + 代表性跨界案例」, 实时公告抓取为独立增强模块
    L3 基本面拐点  -> 人工叙事(见 C档 note)
    L4 低位启动扫描 -> 读 data/*.json 真实技术字段: distMa250∈[-30%,+20%] & chgYtd<30% & volRatio>1.5
    L5 质量Overlay -> C档 note 标注国产化率/稀缺性/是否真供货
    L6 组合执行  -> 报告末尾纪律

数据:
    A档/L4 = data/*.json 内真实行情(西财/腾讯自选股) ; 时点见各文件 date 字段
    C档 = 产业链共识汇编(需联网核实技术面), 若名字命中 data/*.json 则补真实字段
输出:
    <OUT_DIR>/十五五早筛清单_YYYYMMDD.html
"""
import json, os, glob, sys, datetime

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(WS, "data")
OUT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------- L1 政策主线: 十五五框架(已联网核实《纲要》) ----------
# group, label, universe_keys(在 data/*.json 存在的板块名, 用于 L4 真实扫描)
SECTORS_15_5 = [
    ("六大新兴支柱", "集成电路",        ["半导体", "半导体设备", "先进封装", "存储芯片", "元件", "PCB", "光模块", "光通信"]),
    ("六大新兴支柱", "航空航天",        ["商业航天"]),
    ("六大新兴支柱", "生物医药",        ["创新药"]),
    ("六大新兴支柱", "低空经济",        []),   # universe 待补
    ("六大新兴支柱", "新型储能",        []),   # 光伏在 universe, 储能待补
    ("六大新兴支柱", "智能机器人",      ["人形机器人", "宇树科技概念"]),
    ("六大未来产业", "量子科技",        []),
    ("六大未来产业", "生物制造",        []),
    ("六大未来产业", "绿色氢能/核聚变", []),
    ("六大未来产业", "脑机接口",        []),
    ("六大未来产业", "具身智能",        ["人形机器人", "宇树科技概念"]),
    ("六大未来产业", "6G",              []),
    ("已覆盖其他主线", "AI算力/租赁",   ["算力"]),
    ("已覆盖其他主线", "电力/新型电力系统", ["电力"]),
    ("已覆盖其他主线", "新能源汽车",    []),
    ("已覆盖其他主线", "军工",          []),
    ("已覆盖其他主线", "证券",          ["证券"]),
]

# ---------- C档: 指数外真龙头(产业链共识汇编, 需联网核实技术面) ----------
# 仅列 universe 偏薄/空白的赛道; 半导体等已富者不重复列
CURATED_C = {
    "智能机器人": [
        {"name": "双环传动", "role": " RV 减速器国产替代龙头", "scarcity": "国产化率<30%, 人形机器人用量最大环节", "note": "特斯拉链核心, 已批量供货"},
        {"name": "鸣志电器", "role": " 空心杯电机/步进电机", "scarcity": "灵巧手+关节驱动, 国产化率低", "note": "真实出货, 机构重仓"},
        {"name": "柯力传感", "role": " 六维力传感器", "scarcity": "国产化率极低(<10%), 单机价值高", "note": "人形机器人腕/踝必配"},
        {"name": "奥比中光", "role": " 3D 视觉/结构光", "scarcity": "视觉感知核心, 国产稀缺", "note": "已导入本体厂"},
        {"name": "恒立液压", "role": " 线性执行器/丝杠", "scarcity": "丝杠占整机成本~35%, 国产刚起步", "note": "工程机械液压龙头跨界"},
        {"name": "中大力德", "role": " 行星减速器", "scarcity": "国产替代加速", "note": "宇树/智元供应链"},
        {"name": "五洲新春", "role": " 轴承/丝杠", "scarcity": "丝杠上游", "note": "特斯拉链传闻"},
        {"name": "汉威科技", "role": " 柔性电子皮肤", "scarcity": "触觉传感国产稀缺", "note": "研发送样"},
        {"name": "芯动联科", "role": " MEMS IMU", "scarcity": "姿态感知核心", "note": "军用转民用"},
        {"name": "兆威机电", "role": " 灵巧手微型传动", "scarcity": "灵巧手增量环节", "note": "华为/特斯拉链"},
    ],
    "低空经济": [
        {"name": "万丰奥威", "role": " eVTOL 整机(钻石飞机)", "scarcity": "稀缺整机标的", "note": "量产进度领先"},
        {"name": "中信海直", "role": " 低空运营/通航", "scarcity": "运营牌照稀缺", "note": "深圳试点"},
        {"name": "宗申动力", "role": " 航空发动机/动力", "scarcity": "低空动力核心", "note": "无人机+eVTOL"},
        {"name": "莱斯信息", "role": " 空管系统", "scarcity": "空管信息化国产", "note": "军民融合"},
        {"name": "四川九洲", "role": " 空管/监视", "scarcity": "低空监视设备", "note": "军转民"},
        {"name": "纵横股份", "role": " 工业无人机", "scarcity": "垂直起降固定翼", "note": "行业应用"},
    ],
    "新型储能": [
        {"name": "宁德时代", "role": " 储能电池龙头", "scarcity": "全球储能出货第一", "note": "储能+固态双线"},
        {"name": "赣锋锂业", "role": " 固态电池电解质", "scarcity": "固态路线布局早", "note": "氧化物电解质中试"},
        {"name": "上海洗霸", "role": " 固态电解质(氧化物)", "scarcity": "小市值弹性", "note": "中科院合作"},
        {"name": "金龙羽", "role": " 固态电池(聚合物)", "scarcity": "小市值弹性", "note": "中试线"},
        {"name": "骄成超声", "role": " 固态电池焊接设备", "scarcity": "设备唯一性", "note": "超声波焊接独家"},
    ],
    "量子科技": [
        {"name": "国盾量子", "role": " 量子通信/计算整机", "scarcity": "A股量子唯一整机", "note": "中科大背景"},
        {"name": "科大国创", "role": " 量子云平台", "scarcity": "软件层", "note": "参股国仪量子"},
        {"name": "神州信息", "role": " 量子保密通信集成", "scarcity": "金融量子应用", "note": "银行场景"},
    ],
    "生物制造": [
        {"name": "凯赛生物", "role": " 合成生物长链二元酸", "scarcity": "全球龙头", "note": "产业化成熟"},
        {"name": "华恒生物", "role": " 合成生物氨基酸", "scarcity": "全球领先", "note": "缬氨酸/丙氨酸"},
        {"name": "川宁生物", "role": " 合成生物发酵", "scarcity": "产能规模", "note": "抗生素+合成生物"},
    ],
    "绿色氢能/核聚变": [
        {"name": "亿华通", "role": " 燃料电池系统", "scarcity": "氢能车系统龙头", "note": "冬奥验证"},
        {"name": "宝丰能源", "role": " 绿氢/煤化工", "scarcity": "大规模绿氢示范", "note": "宁夏项目"},
        {"name": "联创光电", "role": " 高温超导(聚变磁体)", "scarcity": "聚变上游稀缺", "note": "西部超导合作"},
    ],
    "脑机接口": [
        {"name": "创新医疗", "role": " 脑机医疗应用", "scarcity": "A股稀缺标的", "note": "参股博灵"},
        {"name": "三博脑科", "role": " 神经外科/脑机", "scarcity": "临床场景", "note": "癫痫/康复"},
        {"name": "南京熊猫", "role": " 脑机概念", "scarcity": "研发中", "note": "边缘, 慎"},
    ],
    "6G": [
        {"name": "中兴通讯", "role": " 6G 标准/设备", "scarcity": "主设备商", "note": "研发领先"},
        {"name": "中国卫通", "role": " 卫星通信(6G 空天地)", "scarcity": "卫星资源稀缺", "note": "6G 空基"},
        {"name": "信维通信", "role": " 天线/射频", "scarcity": "终端射频", "note": "天线阵列"},
    ],
    "AI算力/租赁": [
        {"name": "利通电子", "role": " GPU 算力租赁(已验证)", "scarcity": "转型标杆", "note": "见方法论案例, 6月见顶需避"},
        {"name": "鸿博股份", "role": " 英博数科算力租赁", "scarcity": "早期转型", "note": "波动大"},
        {"name": "恒润股份", "role": " 算力租赁转型", "scarcity": "传统厂跨界", "note": "叙事驱动"},
        {"name": "莲花控股", "role": " 味精厂跨界算力", "scarcity": "极致跨界", "note": "L2 典型, 慎质量"},
    ],
    "商业航天": [
        {"name": "上海瀚讯", "role": " 军用宽带通信", "scarcity": "星座通信", "note": "G60 链"},
        {"name": "铖昌科技", "role": " 相控阵 T/R 芯片", "scarcity": "射频芯片国产", "note": "星载核心"},
        {"name": "臻镭科技", "role": " 射频收发/电源", "scarcity": "星载芯片", "note": "自主可控"},
        {"name": "斯瑞新材", "role": " 火箭材料(铬锆铜)", "scarcity": "箭体材料", "note": "商业火箭供"},
    ],
}

# L4 低位启动阈值
L4 = {"dm250_lo": -30.0, "dm250_hi": 20.0, "ytd_hi": 30.0, "vol_hi": 1.5}


def load_index():
    """name -> stock dict across all data/*.json"""
    idx = {}
    for fp in glob.glob(os.path.join(DATA, "*.json")):
        try:
            d = json.load(open(fp, encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        for u in d.get("universe", []) or []:
            if isinstance(u, dict) and u.get("name"):
                idx[u.get("name")] = u
    return idx


def l4_flag(u):
    dm = u.get("distMa250")
    ytd = u.get("chgYtd")
    vr = u.get("volRatio")
    if None in (dm, ytd, vr):
        return False, ""
    ok = (L4["dm250_lo"] <= dm <= L4["dm250_hi"]) and (ytd < L4["ytd_hi"]) and (vr > L4["vol_hi"])
    reason = []
    if L4["dm250_lo"] <= dm <= L4["dm250_hi"]:
        reason.append(f"距年线{dm:+.1f}%")
    if ytd < L4["ytd_hi"]:
        reason.append(f"YTD{ytd:+.1f}%")
    if vr > L4["vol_hi"]:
        reason.append(f"量比{vr:.2f}")
    return ok, "·".join(reason)


def scan_l4(sector_keys, idx):
    """返回 {sector_file: [stocks flagged]}"""
    out = {}
    for fp in glob.glob(os.path.join(DATA, "*.json")):
        try:
            d = json.load(open(fp, encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        sec = d.get("sector") or d.get("code")
        if sector_keys and sec not in sector_keys:
            continue
        hits = []
        for u in d.get("universe", []) or []:
            ok, why = l4_flag(u)
            if ok:
                hits.append((u, why))
        if hits:
            out[sec] = hits
    return out


def main():
    only = []
    if "--sectors" in sys.argv:
        i = sys.argv.index("--sectors")
        only = [s.strip() for s in sys.argv[i + 1].split(",") if s.strip()]
    idx = load_index()
    today = datetime.date.today().strftime("%Y%m%d")

    # 选赛道
    sectors = [s for s in SECTORS_15_5 if not only or s[1] in only]
    universe_keys = sorted({k for _, _, ks in sectors for k in ks})

    l4 = scan_l4(universe_keys, idx)

    # ---- 渲染 HTML ----
    rows_l4 = []
    for sec, hits in sorted(l4.items()):
        for u, why in hits:
            rows_l4.append(f"""<tr><td>{sec}</td><td>{u.get('name')}</td><td>{u.get('code')}</td>
<td class="num">{u.get('price')}</td><td class="num">{u.get('chgYtd'):+.1f}%</td>
<td class="num">{u.get('distMa250'):+.1f}%</td><td class="num">{u.get('volRatio'):.2f}</td>
<td class="num">{u.get('mcap'):.0f}亿</td><td>{why}</td></tr>""")

    # C档
    c_blocks = []
    for group, label, _ in sectors:
        clist = CURATED_C.get(label, [])
        if not clist:
            continue
        trs = []
        for c in clist:
            u = idx.get(c["name"])
            if u:
                tech = f"距年线{u.get('distMa250'):+.1f}%·YTD{u.get('chgYtd'):+.1f}%·量比{u.get('volRatio'):.2f}"
            else:
                tech = "<span class='warn'>指数外·待核实</span>"
            trs.append(f"""<tr><td>{c['name']}</td><td>{c['role']}</td><td>{c['scarcity']}</td>
<td>{c['note']}</td><td>{tech}</td></tr>""")
        if trs:
            c_blocks.append(f"""<div class="sec"><h3>{label} <span class="tag">{group}</span></h3>
<table><tr><th>标的</th><th>环节/角色</th><th>稀缺性</th><th>质量注记</th><th>技术面</th></tr>
{''.join(trs)}</table></div>""")

    l4_html = "".join(rows_l4) or "<tr><td colspan=9>当前无 L4 低位启动候选（全部已 price-in）</td></tr>"
    c_html = "".join(c_blocks) or "<p>该赛道 C档 待补。</p>"

    html = f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>十五五潜力股早筛清单 {today}</title>
<style>
body{{font-family:-apple-system,'PingFang SC',sans-serif;background:#f5f6fa;color:#1a1a2e;margin:0;padding:24px}}
h1{{background:linear-gradient(135deg,#1a2a6c,#3a1c71);color:#fff;padding:20px 28px;border-radius:12px;margin:0 0 8px}}
.sub{{color:#666;font-size:13px;margin:0 0 20px;padding-left:6px}}
.sec{{background:#fff;border-radius:10px;padding:16px 20px;margin:16px 0;box-shadow:0 2px 8px rgba(0,0,0,.06)}}
h3{{margin:6px 0 12px;color:#1a2a6c}}
.tag{{background:#eeeffb;color:#3a1c71;font-size:11px;padding:2px 8px;border-radius:10px;margin-left:6px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th,td{{border-bottom:1px solid #eee;padding:8px 10px;text-align:left;vertical-align:top}}
th{{background:#fafbff;color:#3a1c71;font-weight:600}}
td.num{{text-align:right;font-variant-numeric:tabular-nums}}
.warn{{color:#c0392b;font-weight:600}}
.note{{background:#fff8e1;border-left:4px solid #f1c40f;padding:12px 16px;border-radius:6px;font-size:13px;margin:16px 0}}
.box{{background:#e8f5e9;border-left:4px solid #2e7d32;padding:12px 16px;border-radius:6px;font-size:13px;margin:16px 0}}
</style></head><body>
<h1>十五五潜力股 · 早筛清单</h1>
<p class="sub">生成日期 {today} ｜ 方法: 《十五五潜力股选股方法论》L1–L6 ｜ L4 数据时点见各板块 data/*.json(date字段) ｜ C档为产业链共识汇编, 技术面需联网核实</p>

<div class="box"><b>用法</b>：本清单是「早于概念指数」的早筛池。A档=L4低位启动(已是 universe 内、尚未启动的票)；C档=指数外真龙头(超额收益主来源, 待补 universe 或单独跟踪)；L2=新晋跨界公告扫描(见下方方法)。</div>

<h2>① L4 低位启动候选（真实数据·来自 universe 内未启动票）</h2>
<div class="sec"><table>
<tr><th>板块</th><th>标的</th><th>代码</th><th>价</th><th>YTD</th><th>距年线</th><th>量比</th><th>市值</th><th>触发原因</th></tr>
{l4_html}
</table></div>

<h2>② C档 · 指数外真龙头（十五五各赛道·超额收益来源）</h2>
{c_html}

<h2>③ L2 新晋跨界/转型扫描（方法 + 代表案例）</h2>
<div class="sec">
<p><b>逻辑</b>：利通电子式「传统厂跨界当年最热主线」是 0→1 早信号。等进概念指数时第一波已走完。</p>
<p><b>执行</b>：每周扫公告/互动易关键词（GPU·智算中心·算力租赁·人形机器人·丝杠·低空·eVTOL·固态电池），过滤「未入对应概念指数 & 市值<100亿 & 近1年低位」，人工过「有无真资产/订单」。</p>
<p><b>已验证代表（2026 真实公告·均不在你 universe 内）</b>：</p>
<ul>
<li><b>兆丰股份</b>(300695, 轴承/轮毂厂, 市值~58亿)：2026-06-23 发 14 亿可转债加码具身机器人（滚柱丝杠/关节模组/谐波减速器），已与乐聚智能合作 → 典型 L2 早信号。</li>
<li><b>震裕科技</b>(模具/结构件厂)：18.8 亿可转债投「人形机器人线性模组+丝杠」（子公司宁波马丁具身），达产 21 万套模组/56 万套丝杠。</li>
<li><b>万向钱潮</b>(万向节龙头)：2025-09 公告机器人业务成第三战略板块，丝杠/轴承获头部客户定点，2026 计划 120 万套机器人轴承产能。</li>
<li><b>五洲新春</b>(轴承厂, 已在 C档)：10 亿定增丝杠，已进特斯拉 Optimus 7 家核心供应商。</li>
</ul>
<p>以上传统厂跨界「丝杠/减速器/模组」是 2026 最密集的 L2 信号，爆发前<strong>几乎都不在你 universe 内</strong>，正是本清单 C档 要补的方向。</p>
<p class="note">⚠️ L2 实时公告抓取为独立增强模块（需公告数据源），本报告给出方法与案例，未做全量自动扫描。建议后续接公告 API 后自动化。</p>
</div>

<div class="note"><b>风险纪律(L6)</b>：① 政策 price-in 已涨的票不追；② 主题退潮破 MA60 即减；③ 基本面证伪（无真订单/纯概念）一票否决；④ C档 指数外票流动性/质量参差，单只小仓、篮子 3-5 只。</div>

<p class="sub">数据源: 腾讯自选股/西财(经 westock-mcp) ｜ 生成: 007-指数行业分析/scripts/early_screen.py ｜ 本报告为研究线索, 非投资建议。</p>
</body></html>"""

    out_path = os.path.join(OUT_DIR, f"十五五早筛清单_{today}.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"OK -> {out_path}")
    print(f"L4 候选: {sum(len(v) for v in l4.values())} 只  | C档赛道: {len([s for s in sectors if CURATED_C.get(s[1])])} 个")


if __name__ == "__main__":
    main()
