"""暗盘资金 G/S 信号（中小单代理 · 明暗背离形态）。

## 它回答什么

「今天有没有票出现**明暗背离** —— 明盘（超大单+大单）方向与中单方向相反」，
并按形态标注 ``G``（拆单吸筹嫌疑）/ ``S``（拉高派发嫌疑）。

## 口径（这是本模块的全部可信度来源，不得省略）

* **明盘** = 东财「主力」= 超大单 + 大单净额（``f62``，与 vanguard 资金维同口径）。
* **暗盘代理** = 中单净流入（``f78``）。小单（``f84``）随行下发但**不参与判定** ——
  小单以真散户为主，噪声更大。
* ⚠️ 中单是**「散户 + 拆单主力」的混合体**，公开数据（含 L2 逐笔）无账户维度，
  无法做真正的拆单归集。本模块只认「方向相反」这一形态，**不产出拆单金额估算**。
* **G/S 是启发式规则**（阈值未回测校准），且**恒定 ``status=unsupported``** ——
  未定义收益口径前不给买卖动作（全站红线），前端必须渲染成「未验证形态」。

## G/S 规则（启发式，单日横截面）

| 信号 | 明盘（主力净额） | 中单净额  | 当日涨幅        | 读法                             |
|------|------------------|-----------|-----------------|----------------------------------|
| G    | 流出 (< 0)       | 流入 (> 0)| −5% ~ 3%        | 明出暗进 + 未拉高 → 拆单吸筹嫌疑 |
| S    | 流入 (> 0)       | 流出 (< 0)| ≥ 3%            | 明进暗出 + 已拉高 → 拉高派发嫌疑 |

G 的涨幅带是**双向**的：深跌日（< −5%）中单流入以散户抄底为主，「吸筹嫌疑」的解读
不成立（实测 −14% 的票会被误标 G），宁可漏判不误判。

另有噪声闸门：``|中单净额 / 成交额| ≥ 2%`` 才出信号（成交额为 0/缺失的行不判）。

## 为什么只做单日

持续性（连续 3-5 日）判据需要**个股**资金流时序，每只票一次请求（``fflow/daykline``），
全市场铺开必触发风控（memory：逐只请求是风控主因）。首版只做横截面，caveat 里
明示「无持续性判据、不可跨日比较」。

## 取数与缓存

复用 ``spot_service.fetch_fund_flow_rows``（东财 clist 批量端点，一次覆盖数百只）：

* 明暗背离的票**必然**在主力净额两端之一（G 在流出侧、S 在流入侧），
  所以拉 f62 两端榜即可覆盖全部候选，不必再按 f78 排序拉两轮。
* 缓存 / force 节流 / 失败冷却与 ``vanguard_service._load_fund_flow`` 同哲学：
  force 节流锚点是**上一次真实取数**（``_last_live_at``），不是上一次 force ——
  否则「普通取数 → 紧跟 force」会直接绕过限流（vanguard 的实测坑）。
"""
from __future__ import annotations

import asyncio
import time

from app.services import spot_service

# ── 与 vanguard_service._load_fund_flow 同一套参数哲学 ──────────────────
_TTL = 600                 # 横截面是慢变量，10 分钟够用
_FAIL_COOLDOWN = 180       # 端点失败后的实例冷却（同源东财 push2，重试只会延长封禁）
_FORCE_MIN_INTERVAL = 60   # force 穿透的最小间隔（防连点）

# ── G/S 判定阈值（启发式，未回测校准 —— 调整必须同步改 CAVEATS 文案）──
_MID_MIN_PCT_OF_AMOUNT = 2.0   # 中单净额占成交额最小比例（%），低于此视为噪声
_G_MIN_CHANGE_PCT = -5.0       # G：当日涨幅下限 —— 深跌日中单流入以散户抄底为主，
                               # 「吸筹嫌疑」的解读不成立（实测 -14% 的票会被误标 G），宁可漏判
_G_MAX_CHANGE_PCT = 3.0        # G：当日涨幅上限（还没拉高）
_S_MIN_CHANGE_PCT = 3.0        # S：当日涨幅下限（已经拉高）
_SIDE_SIZE = 10                # 每侧展示条数

# 与 sector_flow_service.CAVEATS 同角色：随接口下发，前端必须渲染。
CAVEATS = [
    "暗盘代理口径：中单（f78）是「散户 + 拆单主力」的混合体，公开数据无账户维度、拆不开，不是真实暗盘成交。",
    "G/S 是「明暗背离」形态识别（明盘大单与中单方向相反），不是拆单金额估算。",
    "阈值为启发式、未回测校准；未定义收益口径，G/S 恒为 unsupported，不是买卖建议。",
    "单日横截面读数：无持续性判据（连续 3-5 日需要个股时序，未接），不可跨日比较。",
]

_cache: tuple[float, dict] | None = None  # (写入时刻 monotonic, 载荷)
_failed_at: float | None = None
_last_live_at: float | None = None


def _mid_pct(row: dict) -> float | None:
    """中单净额占成交额比例（%）。分母缺失/为 0 时返回 None（不判信号）。"""
    mid = row.get("mid_net")
    amount = row.get("amount")
    if mid is None or not amount:
        return None
    return mid / amount * 100.0


def _classify(row: dict) -> dict | None:
    """单行 → G/S 信号条目，或 None（不构成背离形态）。

    信号条目只带读数字段；``actionable`` / ``status`` 由装配层统一钉死，
    不从规则里来 —— 防止未来加规则时漏标 unsupported。
    """
    main = row.get("main_net")
    mid = row.get("mid_net")
    chg = row.get("change_pct")
    if main is None or mid is None or chg is None:
        return None

    pct = _mid_pct(row)
    if pct is None or abs(pct) < _MID_MIN_PCT_OF_AMOUNT:
        return None

    signal: str | None = None
    reason: str | None = None
    if main < 0 < mid and _G_MIN_CHANGE_PCT <= chg <= _G_MAX_CHANGE_PCT:
        signal = "G"
        reason = (
            f"明盘净流出 {main / 1e8:.2f}亿 + 中单净流入 {mid / 1e8:.2f}亿"
            f"（占成交额 {pct:.1f}%），涨幅 {chg:.1f}% 未拉高 —— 拆单吸筹嫌疑"
        )
    elif main > 0 > mid and chg >= _S_MIN_CHANGE_PCT:
        signal = "S"
        reason = (
            f"明盘净流入 {main / 1e8:.2f}亿 + 中单净流出 {mid / 1e8:.2f}亿"
            f"（占成交额 {pct:.1f}%），涨幅 {chg:.1f}% 已拉高 —— 拉高派发嫌疑"
        )
    else:
        return None

    return {
        "code": row.get("code"),
        "name": row.get("name"),
        "price": row.get("price"),
        "change_pct": chg,
        "sector": row.get("sector"),
        "main_net": main,
        "mid_net": mid,
        "small_net": row.get("small_net"),
        "amount": row.get("amount"),
        "mid_pct": round(pct, 2),
        "signal": signal,
        "reason": reason,
    }


def _empty_payload(status: str, note: str, fetched_at: float | None = None) -> dict:
    return {
        "status": status,
        "available": False,
        "signal_status": "unsupported",
        "actionable": False,
        "note": note,
        "caliber": "中小单代理（明暗背离形态）",
        "caveats": list(CAVEATS),
        "g_items": [],
        "s_items": [],
        "counts": {"g": 0, "s": 0, "scanned": 0},
        "fetched_at": fetched_at,
    }


def _build_payload(rows: list[dict], note: str, fetched_at: float | None) -> dict:
    g_items: list[dict] = []
    s_items: list[dict] = []
    for row in rows:
        item = _classify(row)
        if not item:
            continue
        (g_items if item["signal"] == "G" else s_items).append(item)

    # 金额大的那批才有信息量（与 vanguard._fund_map 同哲学）；金额相同再按占比稳序。
    g_items.sort(key=lambda r: (r["mid_net"] or 0), reverse=True)
    s_items.sort(key=lambda r: (r["mid_net"] or 0))
    g_items = g_items[:_SIDE_SIZE]
    s_items = s_items[:_SIDE_SIZE]

    return {
        "status": "ok",
        "available": True,
        # ⚠️ 红线：未定义收益口径前不给买卖动作。这两个字段恒定钉死，
        # 前端据「signal_status=unsupported」渲染未验证形态，不得渲染成买卖建议。
        "signal_status": "unsupported",
        "actionable": False,
        "note": note,
        "caliber": "中小单代理（明暗背离形态）",
        "caveats": list(CAVEATS),
        "g_items": g_items,
        "s_items": s_items,
        "counts": {"g": len(g_items), "s": len(s_items), "scanned": len(rows)},
        "fetched_at": fetched_at,
    }


async def get_signals(force: bool = False) -> dict:
    """暗盘资金 G/S 信号载荷（结构完整，取数失败也带 caveats 降级返回）。

    status:
      * ``ok``        本次真拉成功
      * ``cached``    命中内存缓存（含 force 节流窗口内的「返回上次结果」）
      * ``cooldown``  行情源共享冷却期，本次跳过（不视为失败、不延长冷却）
      * ``unavailable`` 拉取失败（本模块已进入冷却）
    """
    global _cache, _failed_at, _last_live_at
    now = time.monotonic()

    if _cache and now - _cache[0] < _TTL:
        if not force:
            return {**_cache[1], "status": "cached"}
        if _last_live_at is not None and now - _last_live_at < _FORCE_MIN_INTERVAL:
            return {
                **_cache[1],
                "status": "cached",
                "note": "刷新间隔过短，返回上次结果",
            }

    if _failed_at is not None and now - _failed_at < _FAIL_COOLDOWN:
        remaining = int(_FAIL_COOLDOWN - (now - _failed_at))
        if _cache:
            return {
                **_cache[1],
                "status": "unavailable",
                "available": True,
                "note": f"资金流端点冷却中（{remaining}s），返回上次结果",
            }
        return _empty_payload("unavailable", f"资金流端点冷却中（{remaining}s）")

    # 与全市场快照同一批东财域名：共享冷却期内撞端点只会延长封禁（vanguard 同款守卫）。
    # 函数内延迟导入避免 market ↔ 本模块的循环导入。
    from app.routes import market as market_routes

    cooling = await market_routes.spot_cooldown_seconds()
    if cooling > 0:
        if _cache:
            return {
                **_cache[1],
                "status": "cooldown",
                "available": True,
                "note": f"行情源被风控，冷却中（{int(cooling)}s），返回上次结果",
            }
        return _empty_payload("cooldown", f"行情源被风控，冷却中（{int(cooling)}s）")

    inflow, outflow = await asyncio.gather(
        asyncio.to_thread(spot_service.fetch_fund_flow_rows, "f62", False),
        asyncio.to_thread(spot_service.fetch_fund_flow_rows, "f62", True),
        return_exceptions=True,
    )

    merged: dict[str, dict] = {}
    ok_sides = 0
    for side in (inflow, outflow):
        if isinstance(side, BaseException) or not isinstance(side, list):
            continue
        ok_sides += 1
        for row in side:
            code = row.get("code")
            if code and code not in merged:
                merged[code] = row

    if not merged:
        _failed_at = now
        return _empty_payload(
            "unavailable",
            f"资金流端点不可用（流入侧 {type(inflow).__name__} / 流出侧 {type(outflow).__name__}）",
        )

    rows = list(merged.values())
    note = "两侧批量榜已合并（G 候选出自流出侧、S 候选出自流入侧）"
    payload = _build_payload(rows, note, fetched_at=now)
    if ok_sides < 2:
        payload["note"] = f"{note}；仅 {ok_sides}/2 侧取到数据"
    _cache = (now, payload)
    _last_live_at = now
    _failed_at = None
    return payload


def clear_caches() -> None:
    """测试隔离用。"""
    global _cache, _failed_at, _last_live_at
    _cache = None
    _failed_at = None
    _last_live_at = None
