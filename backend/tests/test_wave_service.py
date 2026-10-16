"""波浪定位（wave_service）的守卫测试。

这一组测试锁的是**算法与口径**，不是具体数值：

1. ZigZag 必须真的产出摆动点。
   曾经的三态（trend 0/1/-1）写法在 trend==0 时「找高点」和「找低点」两个分支
   同时成立，极值被每根 K 线反复重置 —— 真实上证 500 根 K 线跑出 **0 个**摆动点，
   整块功能静默返回 unknown，界面上什么都不显示。这是最贵的一类失效：
   不报错、不告警，只是没有结论。
2. 「第 4 浪不与第 1 浪重叠」的参数顺序。
   该规则曾写成 `beyond(p1, p4, ...)`（等价于 p1 ≤ p4），恰好把「重叠」判成「合规」，
   于是这条最硬的铁律在真实数据上**永远通过**。用一对只差 p4 的样本钉死它。
3. 「C 浪内部第几子浪」的读法：嵌套读法（A-B-C 且 C 内部 5 子浪）要能命中 c1~c5。
4. 结论必须带级别、带置信度、带逐条铁律（可复核，不是黑箱）。
5. **波浪读数不得进入方向链路**：不进 `ctx`（LLM 上下文）、不改 `evidence_score`。
   这条是模块存在的意义 —— 波浪分级且主观，一旦进证据分，方向标签会跟着漂移。
"""
from __future__ import annotations

import datetime as dt

from app.services import market_prediction as mp
from app.services import regime_service, wave_service as ws


def pack(prices: list[float]) -> list[dict]:
    """把一串收盘价铺成 K 线（日期连续，只保证 Z 字序列结构）。"""
    d0 = dt.date(2026, 1, 1)
    return [
        {
            "date": (d0 + dt.timedelta(days=i)).isoformat(),
            "open": p,
            "high": p,
            "low": p,
            "close": p,
            "volume": 1e8,
        }
        for i, p in enumerate(prices)
    ]


def ramp(points: list[float], bars_per_leg: int = 12) -> list[float]:
    """拐点 → 线性插值成日线序列。"""
    out: list[float] = []
    for i in range(len(points) - 1):
        a, b = points[i], points[i + 1]
        for k in range(bars_per_leg):
            out.append(a + (b - a) * k / bars_per_leg)
    out.append(points[-1])
    return out


def legs_from(prices: list[float]) -> list[dict]:
    """按 H/L 交替直接造摆动点 → 浪腿（绕开 ZigZag，只测浪型判定本身）。"""
    pivots = [
        {
            "index": i,
            "date": f"2026-01-{i + 1:02d}",
            "price": p,
            "kind": "H" if i % 2 == 0 else "L",
        }
        for i, p in enumerate(prices)
    ]
    return ws._legs(pivots)


# 大 A 浪下跌 → 大 B 浪反弹 → C 浪（c1 急跌 / c2 反弹 / c3 主跌进行中）
C_IN_PROGRESS = pack(ramp([3700, 3400, 3600, 3310, 3450, 2900]))
# 完整 C 浪：c1~c5
C_COMPLETE = pack(ramp([3700, 3400, 3600, 3310, 3450, 2900, 3050, 2760], bars_per_leg=10))
# 上行推动浪 1~5（前面先来一段下跌，好让起点低点被识别）
IMPULSE_UP = pack(ramp([3600, 2700, 3500, 3100, 4100, 3700, 4500]))


# ---------------------------------------------------------------- ① ZigZag


def test_zigzag_必须产出摆动点且严格交替() -> None:
    bars = pack(ramp([3700, 3400, 3600, 3310, 3450, 2900]))
    pivots = ws.zigzag(bars, 0.03)

    assert len(pivots) >= 5, f"只识别出 {len(pivots)} 个摆动点 —— ZigZag 又退化了"
    kinds = [p["kind"] for p in pivots]
    assert all(kinds[i] != kinds[i + 1] for i in range(len(kinds) - 1)), "H/L 必须严格交替"
    idx = [p["index"] for p in pivots]
    assert idx == sorted(idx) and len(set(idx)) == len(idx), "索引必须严格递增且不重复"
    # 最后一个点是「当前这一段」的极值，必须标记为未确认
    assert pivots[-1].get("provisional") is True


def test_zigzag_首个高点取区间真实极值而不是扫描末位() -> None:
    # 先涨后跌、跌途中有小反弹：真正的顶是 4000，不是触发阈值那一根
    bars = pack([3000, 3800, 4000, 3900, 3600, 3700, 3400, 3500, 3200])
    pivots = ws.zigzag(bars, 0.08)
    highs = [p for p in pivots if p["kind"] == "H"]
    assert highs, "应当至少识别出一个高点"
    assert (highs[0]["index"], highs[0]["price"]) == (2, 4000)


def test_zigzag_补回序列起点的摆动点_否则标准5浪被误判成ABC() -> None:
    """回归守卫：状态机只在「价格从极值反向走满阈值」时才确认摆动点，于是序列起点
    永远等不到确认（它前面没有数据可供反向走）。实测 `100→120→110→150→135→160`
    这 6 个摆动点曾只识别出 5 个，一个**完整的 5 浪推动浪**因此被误判成 A-B-C。"""
    bars = pack(ramp([100, 120, 110, 150, 135, 160]))
    pivots = ws.zigzag(bars, 0.05)
    assert len(pivots) == 6, f"应识别出含起点在内的 6 个摆动点，实际 {[(p['index'], p['kind']) for p in pivots]}"
    assert (pivots[0]["index"], pivots[0]["kind"], pivots[0]["price"]) == (0, "L", 100)

    res = ws.analyze(bars, "daily")
    assert res["pattern"] == "impulse"
    assert res["position"] == "5"
    assert [w["label"] for w in res["waves"]] == ["1", "2", "3", "4", "5"]


def test_zigzag_首段不足一个阈值时不补起点() -> None:
    """补起点不能把噪声首段当成一浪 —— 那恰恰是 ZigZag 惯例不锚定起点的原因。"""
    # 起点 3000 → 首个确认高点 3200 只有 6.7%，不够 8% 阈值 → 不该锚定起步点
    bars = pack([3000, 3020, 3200, 2800, 3100])
    pivots = ws.zigzag(bars, 0.08)
    assert pivots and pivots[0]["index"] != 0, "首段只有 6.7% 波动，不该被补成摆动点"
    assert (pivots[0]["kind"], pivots[0]["price"]) == ("H", 3200)


def test_zigzag_起点本身就是极值时不会重复补一个点() -> None:
    """起点已在首个摆动点上（价格从起点一路跌）时，补回逻辑必须认出并跳过，
    否则会插入一个与首点同价的假摆动点、把腿数整体错位。"""
    bars = pack(ramp([4000, 3000, 3500, 3100, 3600]))
    pivots = ws.zigzag(bars, 0.05)
    assert (pivots[0]["index"], pivots[0]["kind"], pivots[0]["price"]) == (0, "H", 4000)
    idx = [p["index"] for p in pivots]
    assert len(set(idx)) == len(idx), f"索引不得重复：{idx}"


def test_zigzag_阈值过大时不给摆动点而不是硬凑() -> None:
    # 100 根横盘：任何阈值都不该造出浪型
    bars = pack([3000 + (i % 3) for i in range(100)])
    assert ws.zigzag(bars, 0.05) == []


# ---------------------------------------------------------------- ② 铁律


def _rule(legs: list[dict], name: str) -> dict:
    fit = ws._eval_impulse(legs, ws._IMPULSE_LABELS)
    found = [r for r in fit["rules"] if r["name"] == name]
    assert found, f"没有产出规则「{name}」"
    return found[0]


def test_第4浪不与第1浪重叠_重叠时必须判否() -> None:
    """回归守卫：参数顺序写反时这条规则会恒为 True（最硬的一条铁律形同虚设）。"""
    # 1 浪 4000→3600；3 浪 3900→3100；4 浪反弹到 3660 —— 已越过 1 浪终点 3600（+1.7%）
    overlapping = legs_from([4000, 3600, 3900, 3100, 3660, 2950])
    assert _rule(overlapping, "第4浪不与第1浪重叠")["ok"] is False

    # 对照：4 浪只反弹到 3560（低于 1 浪终点 3600）→ 合规
    ok_case = legs_from([4000, 3600, 3900, 3100, 3560, 2950])
    assert _rule(ok_case, "第4浪不与第1浪重叠")["ok"] is True


def test_容忍指数常见的轻微重叠_超过1pct才算结构性重叠() -> None:
    # 4 浪终点 3620 越过 1 浪终点 3600 仅 0.56% —— 按 _OVERLAP_TOL 放行
    slight = legs_from([4000, 3610, 3900, 3100, 3620, 2950])
    assert _rule(slight, "第4浪不与第1浪重叠")["ok"] is True


def test_第3浪不是最短_最短时必须判否() -> None:
    # 1 浪 400 点、3 浪 200 点、5 浪 420 点 → 3 浪最短
    shortest_third = legs_from([4000, 3600, 3900, 3700, 3820, 3400])
    assert _rule(shortest_third, "第3浪不是最短")["ok"] is False


def test_第2浪不破第1浪起点_回撤超过起点时判否() -> None:
    # 下跌推动浪里 2 浪反弹回到 4050，已越过 1 浪起点 4000
    broken = legs_from([4000, 3600, 4050, 3100, 3560, 2950])
    assert _rule(broken, "第2浪不破第1浪起点")["ok"] is False


def test_有铁律没过时置信度被压到低位() -> None:
    broken = legs_from([4000, 3600, 4050, 3100, 3560, 2950])
    fit = ws._eval_impulse(broken, ws._IMPULSE_LABELS)
    assert fit["required_ok"] is False
    assert fit["confidence"] <= 0.30, "没过铁律的划分不得给出高置信度"


# ---------------------------------------------------------------- ②b 通过率口径


def _impulse_fit(prices: list[float]) -> dict:
    return ws._eval_impulse(legs_from(prices), ws._IMPULSE_LABELS)


def test_通过率分母用满编项数_短结构拿不到满分() -> None:
    """回归守卫：分母若用「当前产出的铁律数」，看得越少越容易满分。

    `_eval_impulse` 按腿数产出铁律（2 腿 1 条 / 3 腿 3 条 / 4 腿 4 条 / 5 腿 5 条），
    改前 2 腿的通过率就是 1/1 = 100%，置信度 0.685 —— 跟「走完 5 浪」几乎一样可信。
    """
    pass_rates = [
        _impulse_fit([4000, 3600, 3800])["required_pass"],
        _impulse_fit([4000, 3600, 3900, 3100])["required_pass"],
        _impulse_fit([4000, 3600, 3900, 3100, 3560])["required_pass"],
        _impulse_fit([4000, 3600, 3900, 3100, 3560, 2950])["required_pass"],
    ]
    assert pass_rates == sorted(pass_rates), f"通过率必须随腿数单调递增，实际 {pass_rates}"
    assert pass_rates[0] == 0.2 and pass_rates[-1] == 1.0, f"2 腿应为 1/5、5 腿才满编，实际 {pass_rates}"
    assert len(set(pass_rates)) == len(pass_rates), f"各腿数的通过率不得相同（改前 2~5 腿会一起挤到 1.0）：{pass_rates}"


def test_两腿的AB划分置信度必须显著低于满编结构() -> None:
    """回归守卫：2 条腿的 A-B 划分曾拿到 0.76 —— 只比走完 5 浪的 0.83 低 0.07，
    界面上同样呈现为一个可信读数。它现在必须掉到 0.55 以下。"""
    ab = ws._eval_abc(legs_from([4000, 3600, 3800]), ws._ABC_LABELS)
    full_abc = ws._eval_abc(legs_from([4000, 3600, 3800, 3300]), ws._ABC_LABELS)
    assert ab["required_pass"] < full_abc["required_pass"], "残缺的 A-B 通过率不该等于完整的 A-B-C"
    assert ab["confidence"] < 0.55, f"2 腿 A-B 置信度仍偏高：{ab['confidence']}"

    short_impulse = _impulse_fit([4000, 3600, 3800])
    assert short_impulse["confidence"] <= 0.30, f"2 腿的 1-2 浪置信度仍偏高：{short_impulse['confidence']}"


def test_部分结构不算未全过_四腿的一二三四浪必须放行() -> None:
    """``required_ok`` 只看当前能评估的项：4 条腿的 1-2-3-4 是合法的**部分**结构，
    不该因为「还没走到第 5 浪」被判成没全过、进而被压到 ≤0.30。"""
    fit = _impulse_fit([4000, 3600, 3900, 3100, 3560])
    assert fit["required_ok"] is True, "部分结构被误判成「铁律没过」"
    assert fit["confidence"] > 0.30, "部分结构不该被压到低位"
    assert fit["required_pass"] < 1.0, "没走完的推动浪不该拿满通过率"


def test_三条腿时完整ABC应当胜过残缺推动浪() -> None:
    """改前 3 条腿的 impulse 与 abc 通过率都是 1.0、置信度都是 0.811，选版只能靠
    候选列表顺序让 impulse 胜出 —— 而 3 条腿恰好是**走完的** A-B-C、只是**没走完**的推动浪。"""
    legs = legs_from([4000, 3600, 3900, 3100])
    impulse = ws._eval_impulse(legs, ws._IMPULSE_LABELS)
    abc = ws._eval_abc(legs, ws._ABC_LABELS)
    assert abc["confidence"] > impulse["confidence"], "完整 A-B-C 的置信度必须高于残缺推动浪"


def test_满编必过项数与实际产出的铁律数一致() -> None:
    """``_FULL_REQUIRED`` 是通过率的分母。哪天给某个结构加了一条铁律却忘了同步这个
    常量，分母就会小于实际项数、通过率又能冲破 1.0 —— 这条守卫专门拦这个。"""
    full_impulse = _impulse_fit([4000, 3600, 3900, 3100, 3560, 2950])
    n_impulse = sum(1 for r in full_impulse["rules"] if r["required"] and r["applicable"])
    assert n_impulse == ws._FULL_REQUIRED["impulse"], "推动浪满编铁律数与 _FULL_REQUIRED 不符"

    full_abc = ws._eval_abc(legs_from([4000, 3600, 3800, 3300]), ws._ABC_LABELS)
    n_abc = sum(1 for r in full_abc["rules"] if r["required"] and r["applicable"])
    assert n_abc == ws._FULL_REQUIRED["abc"], "A-B-C 满编铁律数与 _FULL_REQUIRED 不符"


# ---------------------------------------------------------------- ③ 浪位识别


def test_识别C浪内部第3子浪() -> None:
    res = ws.analyze_dual(C_IN_PROGRESS)["daily"]
    assert res["pattern"] == "impulse"
    assert res["position"] == "c3", f"应报 c3，实际 {res['position']}（{res['note']}）"
    assert res["position_cn"] and "第 3 子浪" in res["position_cn"]
    assert res["confidence"] > 0.5
    assert res["parent"] is not None, "c1~c5 标签必须带出外层 A-B-C"
    assert res["direction"] == "down"


def test_识别完整C浪的末跌子浪() -> None:
    res = ws.analyze_dual(C_COMPLETE)["daily"]
    assert res["position"] == "c5"
    assert [w["label"] for w in res["waves"]] == ["c1", "c2", "c3", "c4", "c5"]


def test_识别上行推动浪() -> None:
    res = ws.analyze_dual(IMPULSE_UP)["daily"]
    assert res["position"] == "5"
    assert res["direction"] == "up"
    assert [w["label"] for w in res["waves"]] == ["1", "2", "3", "4", "5"]


def test_每个级别都带级别名与口径说明() -> None:
    res = ws.analyze_dual(C_COMPLETE)
    assert set(res) >= {"daily", "weekly", "note"}
    assert res["daily"]["degree"] == "daily"
    assert res["weekly"]["degree"] == "weekly"
    # 界面上必须能读到两条口径：① 波浪是分级的；② 不参与方向分
    assert "分级" in res["note"]
    assert "不参与方向分" in res["note"]


def test_规则逐条回传_可复核不是黑箱() -> None:
    res = ws.analyze_dual(C_COMPLETE)["daily"]
    names = [r["name"] for r in res["rules"]]
    assert "第3浪不是最短" in names
    assert "第4浪不与第1浪重叠" in names
    for r in res["rules"]:
        assert isinstance(r["ok"], bool)
        assert isinstance(r["detail"], str) and r["detail"], f"规则 {r['name']} 没有给可读依据"


def test_样本不足时返回unknown而不是硬凑浪位() -> None:
    res = ws.analyze(pack(ramp([3000, 3200, 3100])), "daily")
    assert res["pattern"] == "unknown"
    assert res["position"] is None
    assert res["note"]


def test_内部异常被吞掉_不向上抛() -> None:
    # 脏数据：日期非法 + close 缺失 + 全是噪声
    bad = [{"date": "not-a-date", "close": None}, {"date": None, "close": "abc"}]
    res = ws.analyze_dual(bad)  # 不得抛异常
    assert res["daily"]["pattern"] == "unknown"
    assert res["weekly"]["pattern"] == "unknown"


# ---------------------------------------------------------------- ④ 双级别


def test_日线结果与周线结果相互独立() -> None:
    res = ws.analyze_dual(pack(ramp([3600, 3000, 3400, 3100, 3800, 3400, 4000, 3600, 4200])))
    # 两条线的输入粒度不同（周线是聚合出来的），至少要保证各自带自己的口径
    assert res["daily"]["bars"] == 8 * 12 + 1
    assert res["weekly"]["bars"] <= res["daily"]["bars"]


# ---------------------------------------------------------------- ⑤ 不进方向链路


def _index_bars(n: int = 180) -> list[dict]:
    return pack(ramp([3400, 3800, 3600, 4100, 3900, 4300, 4100, 4500, 4300, 3900, 4200], bars_per_leg=n // 11 + 1))


def test_波浪读数不进LLM上下文() -> None:
    """模型一旦读到「现在在 C 浪主跌段」就会拿它当方向依据，而 prompt 里的证据分锚点
    又禁止它改方向 —— 结果只会是文案与标签互相打架。所以它只能出现在展示层。"""
    ctx, summary = mp.build_market_context(_index_bars())
    assert "wave" in summary, "波浪读数应当出现在返回给前端的 technical 里"
    assert "浪" not in ctx, f"波浪读数漏进了 LLM 上下文：{[l for l in ctx.splitlines() if '浪' in l]}"


def test_波浪读数不改变证据分() -> None:
    """证据分必须完全由状态分 + 市场宽度决定；加上波浪后数值不得变化。"""
    hist = _index_bars()
    _, summary = mp.build_market_context(hist)
    expected = regime_service.blend_evidence(summary["regime"].get("regime_score"), None)
    assert summary["evidence_score"] == expected


def test_波浪计算抛异常时不影响预测上下文() -> None:
    """辅助读数失败只能降级为 None，绝不能把整条预测链路带崩。"""
    hist = _index_bars()

    original = ws.analyze_dual

    def boom(*_a, **_k):
        raise RuntimeError("模拟波浪计算崩溃")

    ws.analyze_dual = boom
    try:
        ctx, summary = mp.build_market_context(hist)
    finally:
        ws.analyze_dual = original

    assert summary["wave"] is None
    assert summary["evidence_score"] is not None
    assert ctx  # 上下文照常产出
