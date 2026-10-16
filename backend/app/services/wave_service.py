"""艾略特波浪定位：判断指数「当前可能处在第几浪」（只读辅助读数）。

## 为什么单独成模块，且**不进证据分**

``regime_service`` / ``signal_service`` 的产出会汇进 ``evidence_score``，从而决定方向标签；
本模块的产出**不参与方向分**，只回答「按波浪理论现在可能在第几浪」——
与 RSI / 量比同类（见 ``market_prediction.build_market_context`` 里
「技术读数（仅作解释参考，不参与方向分）」那段口径）。

必须隔离的原因：波浪划分是**分级 + 主观**的。
同一段行情在日线看是「C 浪」、在周线看可能只是某段的「a 浪」；摆动阈值微调也会改变浪数。
一旦让它进证据分，方向标签就会随划分漂移，直接破坏
``market_prediction`` 模块 docstring 里那条契约（「方向由量化证据决定」）。

同理，本模块的输出**也不进 LLM prompt**：模型读到「现在在 C 浪主跌段」后极易把它
当成方向依据，而 prompt 里的证据分锚点又禁止模型改方向 —— 结果是文案与标签互相打架。
结构信息只在界面上单独成块展示。

## 口径（三道防线，改之前先读）

1. **必须是可复核的**：所有铁律的通过情况都逐条回传（``rules``），不藏黑箱结论。
   用户看到「现在在 c3」时，能同时看到凭哪几条判定、哪几条没通过。
2. **必须带级别**：对外文案一律是「日线级别 · C 浪第 3 子浪」，不能只写「第 3 浪」——
   否则会和其他周期的划分数混淆。
3. **必须带置信度**：铁律通过率 + 斐波那契贴合度 + 结构完整度合成为 0~1 的置信度。
   置信度低就当它没说 —— 界面按低置信度弱化展示，而不是把猜测当结论。

## 算法

  zigzag()        百分比摆动点识别（价格从极值反向走满阈值才确认一个新摆动点）
  _to_weekly()    日线聚合为周线
  _fit_nested_c() 先试「大 A-B-C 调整 + C 浪内部 5 子浪」的嵌套读法（c1~c5 就是从这来的）
  _fit_direct()   再看整段是否为一条独立的推动浪 / 调整浪
  analyze()       单级别；analyze_dual() 日线 + 周线

选版原则：**优先能解释最多结构、且铁律全过的那一版**；没有全过的版本时退回「最接近」的一版，
并把置信度压到 0.3 以下 + 在 note 里说明没通过全部铁律。
"""
from __future__ import annotations

import datetime as dt
import math

# 摆动点确认阈值（价格从极值反向走满该比例才承认一个新摆动点）。
#
# 不用固定值，而是按波动率自适应：threshold = clamp(近 60 根平均绝对振幅 × 倍数, lo, hi)。
#   lo（下界）—— 低于它会把噪声小段也当成一条浪，尾部结构被切碎，
#                于是「当前在第几浪」每天都在变；
#   hi（上界）—— 高于它时一次普通回调会被整段吞掉，看不到 C 浪内部的子浪，
#                而「C 浪走到第几子浪」恰恰是本模块主要回答的问题。
#
# 倍数与区间是按「上证指数的典型波动」定的初值：日线平均绝对日振幅约 0.8%、
# 周线约 1.8%，×5 与 ×3 后分别落在 4% / 5.4% 附近 —— 与波浪派手工数浪的常用幅度一致。
# 这两个数是经验值，需要回测校准；改之前先看清楚上面的 lo/hi 语义。
_ZIGZAG_MULT = {"daily": 5.0, "weekly": 3.0}
_ZIGZAG_PCT = {"daily": (0.02, 0.06), "weekly": (0.035, 0.09)}

# 最少摆动点数：3 浪调整要 4 个点，5 浪推动要 6 个点。少于 4 个点时直接给 unknown ——
# 用两个点硬凑出「第 1 浪」是最容易发生的假信号。
_MIN_PIVOTS = 4

# 铁律容差：波浪理论允许极小的越界（第 2 浪与第 1 浪起点差几分钱视为相等）。
_TOL = 0.004

# 「第 4 浪不与第 1 浪重叠」单独用更大的容差。
# 教科书口径是零重叠，但指数级别的推动浪在真实数据上常出现 0.5%~1% 的轻微重叠
# （严格零重叠那一版会把绝大多数真实读法判死，整块功能退化成「永远数不出推动浪」）。
# 超过 1% 才算结构性重叠 —— 那种情况按波浪理论已经属于「倾斜三角形」，
# 不该再当成标准推动浪往外报。
_OVERLAP_TOL = 0.012

_MAX_WAVES = 5

# 每种结构「满编」时的必过铁律条数（impulse：R1~R5；abc：R1 B不破A起点、R2 C越过A终点）。
# 置信度里的通过率必须按这个数当分母，见 ``_finish``。
_FULL_REQUIRED = {"impulse": 5, "abc": 2}

_LABELS_CN = {
    "1": "第 1 浪（推动）",
    "2": "第 2 浪（回调）",
    "3": "第 3 浪（主升/主跌，通常最长）",
    "4": "第 4 浪（整理）",
    "5": "第 5 浪（末段）",
    "A": "A 浪（调整第一段）",
    "B": "B 浪（逆向的反弹/回抽段，常见诱多诱空）",
    "C": "C 浪（调整末段，下跌场景下即主跌段）",
    "c1": "C 浪第 1 子浪（急跌）",
    "c2": "C 浪第 2 子浪（反弹修正，最后逃命位）",
    "c3": "C 浪第 3 子浪（主跌段，跌幅最大）",
    "c4": "C 浪第 4 子浪（整理/小反弹）",
    "c5": "C 浪第 5 子浪（末跌，常见底背离）",
}

_IMPULSE_LABELS = ["1", "2", "3", "4", "5"]
_ABC_LABELS = ["A", "B", "C"]
_C_LABELS = ["c1", "c2", "c3", "c4", "c5"]

# 斐波那契参照档位
_FIB_RETRACE = (0.236, 0.382, 0.5, 0.618, 0.786)
_FIB_EXTEND = (1.0, 1.618, 2.618)


def _num(value, default: float = 0.0) -> float:
    """安全转 float：脏数据一律当缺失，不抛异常。"""
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def _pct(a: float, b: float) -> float:
    return (a / b - 1) * 100 if b else 0.0


def _nearest_gap(ratio: float, refs: tuple[float, ...]) -> float:
    """比值到最近参照档的相对距离（0 = 完全贴合，1 = 差一倍）。"""
    if ratio <= 0:
        return 1.0
    return min(abs(ratio - r) / r for r in refs)


# ---------------------------------------------------------------- 摆动点识别


def zigzag(bars: list[dict], threshold_pct: float) -> list[dict]:
    """百分比 ZigZag：价格从极值反向走满 threshold_pct 才承认一个新的摆动点。

    返回按时间升序、H/L 严格交替的摆动点列表。最后一个点标记 ``provisional=True``
    —— 它代表「当前这一段还没走完」，正是判断「现在在第几浪」必需的那一段
    （否则最后一段永远不可见，只能报上一个已走完的浪，等于总是滞后一浪）。

    实现要点（改这一段前先读，踩过）：**必须用「下一个摆动点应该是高还是低」的状态机**，
    不能用「趋势方向 trend」的三态写法。曾经的写法在 trend==0（还没定方向）时
    「找高点」和「找低点」两个分支同时成立，导致极值被每一根 K 线反复重置，
    结果是**一个摆动点都识别不出来**（真实上证 500 根 K 线跑出 0 个点，
    进而整块功能静默返回 unknown）。

    确认摆动点时，用「该段区间内的真实极值」而不是扫描途中的运行极值 ——
    价格可能是「先跌到 X、反弹、再跌到略高于 X 的位置」才触发阈值，
    此时真正的低点是 X，用运行极值会把它记成最后一根。

    用收盘价而非最高/最低价：与 ``signal_service.compute_signals`` 的输入口径一致，
    且指数的日内影线常由跳空造成，用影线定位摆动点会把结构切碎。
    """
    pts = [(_num(b.get("close")), str(b.get("date"))[:10]) for b in bars]
    closes = [p for p, _ in pts]
    if len(closes) < 2 or threshold_pct <= 0:
        return []

    pivots: list[dict] = []
    expect: str | None = None  # None/H = 下一个摆动点应是高点；L = 应是低点
    hi_i = lo_i = 0
    hi_p = lo_p = closes[0]

    for i, p in enumerate(closes):
        if p >= hi_p:
            hi_i, hi_p = i, p
        if p <= lo_p:
            lo_i, lo_p = i, p

        if expect in (None, "H"):
            if p <= hi_p * (1 - threshold_pct):
                pivots.append({"index": hi_i, "date": pts[hi_i][1], "price": hi_p, "kind": "H"})
                expect = "L"
                seg = closes[hi_i : i + 1]  # 从高点起重新跟踪低点，避开区间中途的更低点
                lo_p = min(seg)
                lo_i = hi_i + seg.index(lo_p)
        elif p >= lo_p * (1 + threshold_pct):
            pivots.append({"index": lo_i, "date": pts[lo_i][1], "price": lo_p, "kind": "L"})
            expect = "H"
            seg = closes[lo_i : i + 1]
            hi_p = max(seg)
            hi_i = lo_i + seg.index(hi_p)

    # 收尾：把「当前正在走的这一段」的极值挂上去（未确认）
    if expect == "L" and (not pivots or lo_i > pivots[-1]["index"]):
        pivots.append({"index": lo_i, "date": pts[lo_i][1], "price": lo_p, "kind": "L", "provisional": True})
    elif expect == "H" and (not pivots or hi_i > pivots[-1]["index"]):
        pivots.append({"index": hi_i, "date": pts[hi_i][1], "price": hi_p, "kind": "H", "provisional": True})

    # 补回序列最左端的那个极值。
    #
    # 上面的状态机只在「价格从极值反向走满阈值」时才确认摆动点，于是序列起点永远等不到
    # 确认 —— 而它可能正是一浪的起点。实测：`100→120→110→150→135→160`（6 个摆动点）
    # 只识别出 5 个，一个标准的 5 浪推动浪因此被误判成 A-B-C。
    #
    # 只在「起点到第一个摆动点之间本身就够一个阈值幅度」时才补 —— 否则会把一段不满足
    # 阈值的噪声首段当成一浪，而那恰恰是 ZigZag 惯例不锚定起点的原因。
    if pivots:
        first = pivots[0]
        head = closes[: first["index"] + 1]
        p0 = closes[0]
        if abs(first["price"] - p0) >= p0 * threshold_pct:
            if first["kind"] == "H" and p0 <= min(head):
                pivots.insert(0, {"index": 0, "date": pts[0][1], "price": p0, "kind": "L"})
            elif first["kind"] == "L" and p0 >= max(head):
                pivots.insert(0, {"index": 0, "date": pts[0][1], "price": p0, "kind": "H"})
    return pivots


def _legs(pivots: list[dict]) -> list[dict]:
    """摆动点 → 相邻两点的连线（一条"浪腿"）。"""
    out: list[dict] = []
    for i in range(len(pivots) - 1):
        a, b = pivots[i], pivots[i + 1]
        out.append(
            {
                "from_index": a["index"],
                "to_index": b["index"],
                "from_date": a["date"],
                "to_date": b["date"],
                "from_price": _num(a["price"]),
                "to_price": _num(b["price"]),
                "direction": "down" if _num(b["price"]) < _num(a["price"]) else "up",
                "pct": round(_pct(_num(b["price"]), _num(a["price"])), 2),
                "bars": b["index"] - a["index"],
                "provisional": bool(b.get("provisional")),
            }
        )
    return out


def _adaptive_threshold(bars: list[dict], degree: str) -> float:
    """按近 60 根的平均绝对振幅把阈值卡在一个合理区间（见 ``_ZIGZAG_PCT`` 上方注释）。"""
    closes = [_num(b.get("close")) for b in bars if _num(b.get("close")) > 0]
    lo, hi = _ZIGZAG_PCT[degree]
    if len(closes) < 20:
        return hi
    window = closes[-60:]
    moves = [abs(window[i] / window[i - 1] - 1) for i in range(1, len(window)) if window[i - 1]]
    avg = sum(moves) / len(moves) if moves else 0
    return max(lo, min(hi, avg * _ZIGZAG_MULT[degree]))


# ---------------------------------------------------------------- 浪型评估


def _rule(name: str, ok: bool, detail: str, applicable: bool = True, required: bool = True) -> dict:
    return {"name": name, "ok": bool(ok), "detail": detail, "applicable": applicable, "required": required}


def _eval_impulse(legs: list[dict], labels: list[str]) -> dict:
    """评估一段"推动浪"结构（2~5 条腿，第一条腿的方向即整段的趋势方向）。

    波浪铁律（做空方向；做多镜像）：
      R1 第 2 浪不能回撤超过第 1 浪起点     → 违反即不成立（那不是 2 浪，是反转）
      R2 第 3 浪必须越过第 1 浪终点         → 未走完时（provisional）不计入必过项
      R3 第 3 浪不能是 1/3/5 中最短的一段   → 波浪理论最硬的一条
      R4 第 4 浪不能与第 1 浪的价格区间重叠  → 重叠说明数浪数错了
      R5 第 5 浪必须创新极值                → 未走完时不计入必过项
    软性项：
      S1 第 2 浪与第 4 浪形态交替（一个深、一个浅）
      S2 各浪比例贴合斐波那契档位
    """
    count = len(legs)
    prices = [legs[0]["from_price"]] + [leg["to_price"] for leg in legs]
    down = legs[0]["direction"] == "down"
    rules: list[dict] = []

    def beyond(a: float, b: float, margin: float) -> bool:
        """a 是否在趋势方向上越过 b（margin>0 表示要求明确越过，<0 表示允许轻微越界）。"""
        if down:
            return a <= b * (1 - margin)
        return a >= b * (1 + margin)

    p0 = prices[0]
    l1 = abs(prices[1] - p0)

    if count >= 2:
        p1, p2 = prices[1], prices[2]
        # 允许 _TOL 的越界：差几分钱在指数上等于相等
        ok = beyond(p2, p0, -_TOL)
        rules.append(_rule("第2浪不破第1浪起点", ok, f"2 浪终点 {p2:.2f} vs 1 浪起点 {p0:.2f}"))
    if count >= 3:
        p1, p3 = prices[1], prices[3]
        fresh = not legs[2]["provisional"]
        rules.append(
            _rule(
                "第3浪越过第1浪终点",
                beyond(p3, p1, _TOL),
                f"3 浪终点 {p3:.2f} vs 1 浪终点 {p1:.2f}" + ("" if fresh else "（3 浪未走完，不计入必过项）"),
                applicable=fresh,
            )
        )

        l3 = abs(prices[3] - prices[2])
        ref = min(l1, abs(prices[5] - prices[4])) if count >= 5 else l1
        rules.append(_rule("第3浪不是最短", l3 >= ref * (1 - _TOL), f"3 浪 {l3:.0f} 点 vs 参照 {ref:.0f} 点"))

    if count >= 4:
        p1, p4 = prices[1], prices[4]
        # ⚠️ 参数顺序是这个 bug 的高发点：判据是「4 浪终点不能进入 1 浪的价格区间」，
        # 对下跌浪即 p4 ≤ p1。曾经写成 beyond(p1, p4, ...)，等价于 p1 ≤ p4 ——
        # 恰好把「重叠」判成「合规」，于是这条最硬的铁律在真实数据上**永远通过**。
        rules.append(
            _rule(
                "第4浪不与第1浪重叠",
                beyond(p4, p1, -_OVERLAP_TOL),
                f"4 浪终点 {p4:.2f} vs 1 浪终点 {p1:.2f}",
            )
        )

        l2 = abs(prices[2] - prices[1])
        l4 = abs(prices[4] - prices[3])
        l3 = abs(prices[3] - prices[2])
        r2 = l2 / l1 if l1 else 0
        r4 = l4 / l3 if l3 else 0
        rules.append(
            _rule(
                "第2/4浪形态交替",
                abs(r2 - r4) >= 0.10,
                f"2 浪回撤 {r2:.0%} vs 4 浪回撤 {r4:.0%}",
                required=False,
            )
        )
    if count >= 5:
        p3, p5 = prices[3], prices[5]
        fresh = not legs[4]["provisional"]
        rules.append(
            _rule(
                "第5浪创新极值",
                beyond(p5, p3, _TOL),
                f"5 浪终点 {p5:.2f} vs 3 浪终点 {p3:.2f}" + ("" if fresh else "（5 浪未走完，不计入必过项）"),
                applicable=fresh,
            )
        )

    fib = _fib_score(legs, down)
    return _finish(count, labels, down, rules, fib, "impulse")


def _eval_abc(legs: list[dict], labels: list[str]) -> dict:
    """评估一段 A-B-C 调整（2~3 条腿）。

      R1 B 浪不能越过 A 浪起点（越过就不是调整，是新一轮趋势）
      R2 C 浪必须越过 A 浪终点（未走完时不计入必过项）
      S1 B 浪回撤比例属于锯齿（0.3~0.8）或平台（0.85~1.05）
      S2 C 浪与 A 浪的长度比落在 0.618~1.618
    """
    count = len(legs)
    prices = [legs[0]["from_price"]] + [leg["to_price"] for leg in legs]
    down = legs[0]["direction"] == "down"
    rules: list[dict] = []

    def beyond(a: float, b: float, margin: float) -> bool:
        if down:
            return a <= b * (1 - margin)
        return a >= b * (1 + margin)

    l_a = abs(prices[1] - prices[0])
    if count >= 2:
        ok = beyond(prices[2], prices[0], -_TOL)
        rules.append(_rule("B浪不破A浪起点", ok, f"B 终点 {prices[2]:.2f} vs A 起点 {prices[0]:.2f}"))
        r_b = abs(prices[2] - prices[1]) / l_a if l_a else 0
        rules.append(
            _rule(
                "B浪回撤比例属锯齿/平台",
                0.30 <= r_b <= 1.05,
                f"B 回撤 A 的 {r_b:.0%}",
                required=False,
            )
        )
    if count >= 3:
        fresh = not legs[2]["provisional"]
        rules.append(
            _rule(
                "C浪越过A浪终点",
                beyond(prices[3], prices[1], _TOL),
                f"C 终点 {prices[3]:.2f} vs A 终点 {prices[1]:.2f}" + ("" if fresh else "（C 浪未走完，不计入必过项）"),
                applicable=fresh,
            )
        )
        r_c = abs(prices[3] - prices[2]) / l_a if l_a else 0
        rules.append(
            _rule("C浪/A浪长度比在0.618~1.618", 0.5 <= r_c <= 1.8, f"C/A = {r_c:.2f}", required=False)
        )

    fib = _fib_score(legs, down)
    return _finish(count, labels, down, rules, fib, "abc")


def _fib_score(legs: list[dict], down: bool) -> float:
    """斐波那契比例贴合度 0~1（只统计能算出来的项）。"""
    count = len(legs)
    prices = [legs[0]["from_price"]] + [leg["to_price"] for leg in legs]
    l1 = abs(prices[1] - prices[0])
    scores: list[float] = []

    if count >= 3:
        l3 = abs(prices[3] - prices[2])
        if l1:
            scores.append(max(0.0, 1 - _nearest_gap(l3 / l1, _FIB_EXTEND) * 2))
    if count >= 4 and l1:
        l2 = abs(prices[2] - prices[1])
        scores.append(max(0.0, 1 - _nearest_gap(l2 / l1, _FIB_RETRACE) * 2))
    if count >= 5:
        l3 = abs(prices[3] - prices[2])
        l5 = abs(prices[5] - prices[4])
        if l3:
            scores.append(max(0.0, 1 - _nearest_gap(l5 / l3, _FIB_EXTEND) * 2))
    return round(sum(scores) / len(scores), 3) if scores else 0.0


def _finish(count: int, labels: list[str], down: bool, rules: list[dict], fib: float, pattern: str) -> dict:
    """把逐条铁律合成为候选结构的得分与置信度。

    ## 「通过率」的分母必须用**满编**项数，不能用当前产出项数

    ``_eval_impulse`` 是**按腿数产出铁律**的：2 条腿只产出 1 条（第2浪不破起点）、
    3 条腿 3 条、4 条腿 4 条、5 条腿 5 条。所以「当前产出项数」在短结构下天然很小，
    拿它当分母会让**看得越少、通过率越容易满分** —— 实测 2 条腿的 A-B 划分
    1/1 = 100%，置信度 **0.76**，只比走完 5 浪的 0.83 低 0.07，界面上却同样是一个
    可信读数。改用满编分母（``_FULL_REQUIRED``）后同一条 A-B 划分降到 **0.485**、
    2 条腿的 1-2 浪降到 **0.245**，通过率随腿数单调递增（1/5 → 3/5 → 4/5 → 5/5）。

    这个分母同时修掉了「引擎分不出完整 A-B-C 与残缺推动浪」的毛病：3 条腿时
    impulse 与 abc 的旧通过率都是 1.0、置信度都是 0.811，选版只能靠候选列表顺序
    让 impulse 胜出 —— 而 3 条腿恰好是**走完的** A-B-C、只是**没走完**的推动浪。

    ## 「是否全过」（``required_ok``）是另一个口径，别合并

    它只看当前能评估的项：4 条腿的 1-2-3-4 浪是合法的**部分**结构，不该因为
    「还没走到第 5 浪」被判成没全过、进而被压到 ≤0.30。所以它不能用
    ``required_pass >= 1.0`` 表达 —— 那会把「部分结构」和「违背铁律」混为一谈。
    """
    required = [r for r in rules if r["required"] and r["applicable"]]
    soft = [r for r in rules if not r["required"]]
    passed = sum(1 for r in required if r["ok"])

    # 分母＝满编必过项数（impulse 5 / abc 2），减掉「产出了但当下评估不了」的项
    # （`applicable=fresh` 那几条斐波那契规则）；漏掉它们等于让结构白背一条罪名。
    full = _FULL_REQUIRED.get(pattern, len(required) or 1)
    skipped = sum(1 for r in rules if r["required"] and not r["applicable"])
    required_pass = passed / max(1, full - skipped)
    required_ok = all(r["ok"] for r in required)

    soft_pass = sum(1 for r in soft if r["ok"]) / len(soft) if soft else 0.5

    # 结构完整度：走完 5 浪才算看了全貌；只看到 2 条腿时不该有高置信度
    completeness = count / _MAX_WAVES
    confidence = 0.55 * required_pass + 0.15 * soft_pass + 0.15 * fib + 0.15 * completeness
    if not required_ok:
        confidence = min(confidence, 0.30)

    return {
        "pattern": pattern,
        "direction": "down" if down else "up",
        "count": count,
        "labels": labels[:count],
        "required_ok": required_ok,
        "required_pass": round(required_pass, 3),
        "soft_pass": round(soft_pass, 3),
        "fib_score": fib,
        "confidence": round(max(0.0, min(0.95, confidence)), 3),
        "rules": rules,
    }


# ---------------------------------------------------------------- 结构选版


def _pick(cands: list[dict]) -> dict | None:
    """选版：铁律全过优先，其次解释的结构最多（浪数最多），再次置信度最高。"""
    if not cands:
        return None
    valid = [c for c in cands if c["required_ok"]]
    if valid:
        return max(valid, key=lambda c: (c["count"], c["confidence"]))
    return max(cands, key=lambda c: (c["required_pass"], c["count"], c["confidence"]))


def _fit_direct(legs: list[dict]) -> dict | None:
    """把尾部若干条腿整体解释成一条推动浪或一段 A-B-C 调整。"""
    total = len(legs)
    cands: list[dict] = []
    for start in range(max(0, total - _MAX_WAVES), total - 1):
        count = total - start
        if count < 2 or count > _MAX_WAVES:
            continue
        seg = legs[start : start + count]
        if len(seg) != count:
            continue
        impulse = _eval_impulse(seg, _IMPULSE_LABELS)
        impulse["start_leg"] = start
        cands.append(impulse)
        if count <= len(_ABC_LABELS):
            abc = _eval_abc(seg, _ABC_LABELS)
            abc["start_leg"] = start
            cands.append(abc)
    return _pick(cands)


def _fit_nested_c(legs: list[dict]) -> dict | None:
    """「大 A-B-C 调整 + C 浪内部 5 子浪」的嵌套读法 —— c1~c5 就是从这来的。

    先把 A（下跌）/B（反弹）定出来，再把 B 顶之后的那串腿当成 C 浪内部的推动浪评估。
    C 浪只有在**锯齿形（5-3-5）**调整里才是 5 子浪；平台型（3-3-5）、
    三角形（3-3-3-3-3）不是 —— 这是不同分析师划分结果打架的根源，
    所以这里不做「一定是 5 子浪」的假定，而是把实际走出来的腿如实标注。
    """
    total = len(legs)
    best: tuple[tuple, dict] | None = None
    for start in range(0, max(0, total - 2)):
        a_leg, b_leg = legs[start], legs[start + 1]
        if a_leg["direction"] != "down" or b_leg["direction"] != "up":
            continue
        p0, p1, p2 = a_leg["from_price"], a_leg["to_price"], b_leg["to_price"]
        if p2 > p0 * (1 + _TOL):  # B 浪越过 A 浪起点就不是调整了
            continue

        inner = legs[start + 2 :]
        count = len(inner)
        if count < 2 or count > _MAX_WAVES:
            continue
        fit = _eval_impulse(inner, _C_LABELS)
        if not fit["required_ok"]:
            continue

        # 外层 A/B 自身的合规性也计一条，避免把任意一次小反弹当成 B 浪
        r_b = (p2 - p1) / (p0 - p1) if p0 > p1 else 0
        abc_ok = 0.30 <= r_b <= 1.05
        fit["parent_rules"] = [
            _rule("B浪回撤A浪的比例合理", abc_ok, f"B 回撤 A 的 {r_b:.0%}（锯齿 30%~80% / 平台 85%~105%）", required=False)
        ]
        fit["abc"] = {
            "a": {"from_date": a_leg["from_date"], "to_date": a_leg["to_date"], "pct": a_leg["pct"]},
            "b": {"from_date": b_leg["from_date"], "to_date": b_leg["to_date"], "pct": b_leg["pct"]},
            "start_leg": start,
        }
        fit["start_leg"] = start + 2
        # 外层比例不合理时降置信度（不做否决，因为「B 浪强于常规」在 A 股很常见）
        if not abc_ok:
            fit["confidence"] = round(fit["confidence"] * 0.75, 3)
            fit["required_ok"] = False

        key = (fit["required_ok"], count, fit["confidence"])
        if best is None or key > best[0]:
            best = (key, fit)
    return best[1] if best else None


# ---------------------------------------------------------------- 目标位推演


def _project_targets(legs: list[dict], labels: list[str], down: bool) -> list[dict]:
    """按斐波那契关系给当前这一浪的常见目标位。

    只给波浪理论里最基础的三档关系，不叠加其它指标 —— 这是"结构推演"不是"预测价"，
    界面上必须与「关键点位（支撑/压力）」分开呈现，别混成一个口径。
    """
    count = len(legs)
    if count < 2:
        return []
    prices = [legs[0]["from_price"]] + [leg["to_price"] for leg in legs]
    last = count - 1
    label = labels[last]
    l1 = abs(prices[1] - prices[0])
    out: list[dict] = []

    def add(ratio_ref: float, mult: float, basis: str) -> None:
        # 下跌浪目标 = 起点 - 参照长度 × 倍数；上涨浪镜像
        price = prices[last] - ratio_ref * mult if down else prices[last] + ratio_ref * mult
        out.append({"label": label, "price": round(price, 2), "basis": basis})

    if label in ("1", "c1") or label == "A":
        return []  # 第 1 浪刚开始，没有可参照的前一浪

    if label in ("2", "c2", "B"):
        # 回撤目标：从起点往回走 38.2% / 61.8%
        for ratio in (0.382, 0.618):
            add(l1, ratio, f"{label} 回撤第1浪的 {ratio:.1%}")
    elif label in ("3", "c3", "C"):
        for mult in (1.0, 1.618):
            add(l1, mult, f"{label} = 第1浪 × {mult:g}")
    elif label in ("4", "c4"):
        l3 = abs(prices[3] - prices[2]) if count >= 4 else l1
        for ratio in (0.236, 0.382):
            add(l3, ratio, f"{label} 回撤第3浪的 {ratio:.1%}")
    elif label in ("5", "c5"):
        for mult in (1.0, 1.618):
            add(l1, mult, f"{label} = 第1浪 × {mult:g}")
    return out[:3]


# ---------------------------------------------------------------- 对外主入口


def _unknown(degree: str, bars: int, note: str) -> dict:
    return {
        "degree": degree,
        "pattern": "unknown",
        "position": None,
        "position_cn": None,
        "direction": None,
        "confidence": 0.0,
        "bars": bars,
        "threshold_pct": None,
        "pivots": [],
        "waves": [],
        "rules": [],
        "targets": [],
        "parent": None,
        "note": note,
    }


def _to_waves(fit: dict, legs: list[dict]) -> list[dict]:
    """候选结构 → 子浪拆解（供界面逐个标注）。"""
    start = fit.get("start_leg", 0)
    out: list[dict] = []
    for i, label in enumerate(fit["labels"]):
        leg = legs[start + i]
        out.append(
            {
                "label": label,
                "label_cn": _LABELS_CN.get(label, label),
                "from_date": leg["from_date"],
                "to_date": leg["to_date"],
                "from_price": round(leg["from_price"], 2),
                "to_price": round(leg["to_price"], 2),
                "pct": leg["pct"],
                "bars": leg["bars"],
                "provisional": leg["provisional"],
                "current": i == len(fit["labels"]) - 1,
            }
        )
    return out


def analyze(bars: list[dict], degree: str = "daily") -> dict:
    """单级别波浪定位。``bars`` 为按时间升序的 K 线（需含 date / close）。"""
    if len(bars) < 30:
        return _unknown(degree, len(bars), "样本不足 30 根 K 线，无法定位浪位。")

    threshold = _adaptive_threshold(bars, degree)
    pivots = zigzag(bars, threshold)
    if len(pivots) < _MIN_PIVOTS:
        return _unknown(
            degree,
            len(bars),
            f"仅识别出 {len(pivots)} 个有效摆动点（阈值 {threshold:.1%}），不足以划分浪型。",
        )

    legs = _legs(pivots)
    nested = _fit_nested_c(legs)
    direct = _fit_direct(legs)
    if nested and (nested["required_ok"] or not direct or not direct["required_ok"]):
        fit = nested
    else:
        fit = direct or nested
    if not fit:
        return _unknown(degree, len(bars), "尾部结构不匹配任何波浪模板。")

    waves = _to_waves(fit, legs)
    current = waves[-1] if waves else None
    position = current["label"] if current else None
    parent = None
    if fit.get("abc"):
        parent = {"pattern": "abc", "label": "C", "label_cn": _LABELS_CN["C"], **fit["abc"]}
        rules = list(fit.get("parent_rules") or []) + fit["rules"]
    else:
        rules = fit["rules"]

    note = (
        f"{degree}级别、ZigZag 阈值 {threshold:.1%}。"
        + ("C 浪内部结构按锯齿形（5-3-5）匹配。" if parent else "")
        + ("该划分未通过全部铁律，仅供参考。" if not fit["required_ok"] else "")
        + ("当前这一浪尚未走完（以最后一个摆动点为界）。" if current and current["provisional"] else "")
    )

    return {
        "degree": degree,
        "pattern": fit["pattern"],
        "position": position,
        "position_cn": _LABELS_CN.get(position or "", None),
        "direction": fit["direction"],
        "confidence": fit["confidence"],
        "bars": len(bars),
        "threshold_pct": round(threshold * 100, 2),
        "pivots": [
            {
                "date": p["date"],
                "price": round(_num(p["price"]), 2),
                "kind": p["kind"],
                "provisional": bool(p.get("provisional")),
            }
            for p in pivots[-8:]
        ],
        "waves": waves,
        "rules": rules,
        "targets": _project_targets(legs[fit.get("start_leg", 0) :], fit["labels"], fit["direction"] == "down"),
        "parent": parent,
        "note": note,
    }


def _to_weekly(bars: list[dict]) -> list[dict]:
    """日线聚合成周线（ISO 周）。用该周最后一个交易日作为标签日期。"""
    out: list[dict] = []
    key: tuple | None = None
    for bar in bars:
        try:
            day = dt.date.fromisoformat(str(bar.get("date"))[:10])
        except ValueError:
            continue
        iso = day.isocalendar()
        cur_key = (iso[0], iso[1])
        close = _num(bar.get("close"))
        if close <= 0:
            continue
        if out and key == cur_key:
            head = out[-1]
            head["high"] = max(head["high"], _num(bar.get("high"), close))
            head["low"] = min(head["low"], _num(bar.get("low"), close))
            head["close"] = close
            head["volume"] += _num(bar.get("volume"))
            head["date"] = str(bar.get("date"))[:10]
        else:
            key = cur_key
            out.append(
                {
                    "date": str(bar.get("date"))[:10],
                    "high": _num(bar.get("high"), close),
                    "low": _num(bar.get("low"), close),
                    "close": close,
                    "volume": _num(bar.get("volume")),
                }
            )
    return out


def analyze_dual(bars: list[dict]) -> dict:
    """日线 + 周线双级别波浪定位。

    双级别是**必须**的：波浪是分级的，只给一个级别会让用户把「周线某段的 a 浪」
    当成「日线 C 浪」，从而对「第几浪」产生根本性误读。
    """
    try:
        daily = analyze(bars, "daily")
    except Exception as exc:  # noqa: BLE001 — 辅助读数不允许影响主链路
        daily = _unknown("daily", len(bars), f"日线波浪计算异常：{exc}")
    try:
        weekly = analyze(_to_weekly(bars), "weekly")
    except Exception as exc:  # noqa: BLE001
        weekly = _unknown("weekly", 0, f"周线波浪计算异常：{exc}")
    return {
        "daily": daily,
        "weekly": weekly,
        "note": (
            "波浪划分分级且主观：同一段行情在日线/周线会有不同浪数，"
            "本读数仅为算法给出的一种划分，不参与方向分，也不构成投资建议。"
        ),
    }
