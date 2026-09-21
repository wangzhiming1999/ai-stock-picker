"""筹码分布（CYQ）服务：自复刻东财算法，不依赖 akshare。

为什么不用 `ak.stock_cyq_em`：它内部是「裸 requests（无 UA）单次请求」东财
kline 接口 + py_mini_racer 跑 JS。实测（2026-09-21）东财对无 UA 请求大量
RemoteDisconnected，akshare 一次不重试导致成功率极低；而带浏览器 UA +
指数退避重试的同一接口实测 5/5 成功。且 CYQ 本质是**纯本地计算**（窗口
120 根 K 线、三角分布、按换手率衰减），K 线里自带换手率——完全没必要在
服务端跑 JS 引擎。

东财 CYQCalculator 复刻要点（与 akshare 1.16.94 内嵌 JS 逐行对齐，实测
000651 当日：获利比例 0.173 vs 官方 0.187、成本/集中度偏差 <1%）：
- factor=150 档；accuracy = max(0.01, (max(high)-min(low))/149)
- avg = (open+close+high+low)/4；turnoverRate = min(1, hsl/100)
- 每根 K 线：先整条分布衰减 x *= (1-tr)，再以 avg 为峰、high/low 为界
  叠加三角形（一字板=矩形面积的一半）
- 获利比例 = 现价以下筹码 / 总筹码
- 平均成本 = 筹码中位数（getCostByChip(total*0.5)），不是加权均值
- 90 成本区间 = [5%, 95%] 分位成本；集中度 = (高-低)/(高+低)

可靠性：每日 TTL 进程内缓存 + 失败冷却（进程级，serverless 多实例各自
冷却可接受）+ 指数退避重试。批量走 gather_limited 配额 8。
"""

from __future__ import annotations

import asyncio
import logging
import math
import threading
import time
from typing import Any

import requests

from app.services import concurrency, data_service

logger = logging.getLogger(__name__)

# 筹码数据日内基本不变（每天收盘后更新一次），缓存一整个交易日
_CHIP_TTL_OK = 6 * 3600
# 失败短缓存：冷却期内不再真拉
_CHIP_TTL_FAIL = 30 * 60
# 失败冷却：连续失败后至少隔这么久才允许下一次真拉（实测东财节点抖动
# 需 10~20s 恢复，15min 是保守值，防止扫描批量连打放大故障）
_COOLDOWN_SECS = 15 * 60
# 进程内缓存上限（42 只池 + 富余），超出淘汰最旧一半
_CACHE_MAX = 200

# 东财 CYQ 复刻参数（与官方一致）
_CYQ_FACTOR = 150
_CYQ_WINDOW = 120
# 单只最大重试（东财节点随机抖动 ~50% 失败率，退避 4 次后残余失败 <7%，
# 再叠加批内「缺谁标谁」，不因单只失败拖垮整批）
_CYQ_RETRIES = 4

_EM_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Referer": "https://quote.eastmoney.com/",
}

_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}
_lock = threading.Lock()
# 冷却表：code -> 失败截止时间戳（进程级）
_cooldown: dict[str, float] = {}


def _in_cooldown(code: str, now: float) -> bool:
    until = _cooldown.get(code)
    return until is not None and now < until


def _mark_cooldown(code: str, now: float) -> None:
    _cooldown[code] = now + _COOLDOWN_SECS
    expired = [c for c, t in _cooldown.items() if t <= now]
    for c in expired:
        _cooldown.pop(c, None)


def _clear_cooldown(code: str) -> None:
    _cooldown.pop(code, None)


def _secid(code: str) -> str:
    """A 股代码 → 东财 secid：6 开头（沪）= 1.x，其余（深/北）= 0.x。"""
    return f"1.{code}" if code.startswith("6") else f"0.{code}"


def _cyq_summary(klines: list[list[str]], index: int) -> dict[str, float] | None:
    """对第 index 根 K 线计算筹码分布指标（复刻东财 CYQCalculator）。"""
    win = klines[max(0, index - _CYQ_WINDOW + 1): index + 1]
    if not win:
        return None
    try:
        kdata = [
            (
                float(r[1]),  # open
                float(r[2]),  # close
                float(r[3]),  # high
                float(r[4]),  # low
                min(1.0, (float(r[10]) / 100.0) or 0.0),  # turnoverRate
            )
            for r in win
        ]
    except (ValueError, IndexError):
        return None

    maxprice = max(k[2] for k in kdata)
    minprice = min(k[3] for k in kdata)
    if maxprice <= 0 or maxprice <= minprice:
        return None
    accuracy = max(0.01, (maxprice - minprice) / (_CYQ_FACTOR - 1))
    xdata = [0.0] * _CYQ_FACTOR

    for o, c, h, l, tr in kdata:
        avg = (o + c + h + l) / 4
        high_idx = int((h - minprice) / accuracy)
        low_idx = math.ceil((l - minprice) / accuracy)
        g0 = (_CYQ_FACTOR - 1) if h == l else 2 / (h - l)
        g1 = int((avg - minprice) / accuracy)
        # 衰减
        for n in range(_CYQ_FACTOR):
            xdata[n] *= 1 - tr
        if h == l:
            # 一字板：矩形面积是三角形的 2 倍
            if 0 <= g1 < _CYQ_FACTOR:
                xdata[g1] += g0 * tr / 2
        else:
            span = h - l
            for j in range(max(0, low_idx), min(_CYQ_FACTOR - 1, high_idx) + 1):
                cur = minprice + accuracy * j
                if cur <= avg:
                    xdata[j] += g0 * tr if abs(avg - l) < 1e-8 else (cur - l) / (avg - l) * g0 * tr
                else:
                    xdata[j] += g0 * tr if abs(h - avg) < 1e-8 else (h - cur) / (h - avg) * g0 * tr

    total = sum(float(f"{x:.12g}") for x in xdata)
    if total <= 0:
        return None
    price = kdata[-1][1]  # 当日收盘

    def cost_by_chip(chip: float) -> float:
        s = 0.0
        for i in range(_CYQ_FACTOR):
            x = float(f"{xdata[i]:.12g}")
            if s + x > chip:
                return minprice + i * accuracy
            s += x
        return minprice + (_CYQ_FACTOR - 1) * accuracy

    below = sum(float(f"{xdata[i]:.12g}") for i in range(_CYQ_FACTOR) if price >= minprice + i * accuracy)
    benefit = 0.0 if total == 0 else below / total
    avg_cost = cost_by_chip(total * 0.5)
    lo90 = cost_by_chip(total * 0.05)
    hi90 = cost_by_chip(total * 0.95)
    conc90 = 0.0 if (lo90 + hi90) == 0 else (hi90 - lo90) / (lo90 + hi90)
    return {
        "profit_ratio": round(benefit, 4),
        "avg_cost": round(avg_cost, 2),
        "cost_90_low": round(lo90, 2),
        "cost_90_high": round(hi90, 2),
        "concentration_90": round(conc90, 4),
    }


def _fetch_chip_one(code: str) -> dict[str, Any] | None:
    """拉 210 根不复权日线并计算逐日筹码指标。失败返回 None（不抛）。"""
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": _secid(code),
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",
        "fqt": "0",
        "end": "20500101",
        "lmt": "210",
    }
    now = time.time()
    payload: dict[str, Any] | None = None
    for attempt in range(_CYQ_RETRIES):
        try:
            resp = requests.get(url, params=params, headers=_EM_HEADERS, timeout=8)
            resp.raise_for_status()
            payload = resp.json()
            break
        except Exception as e:  # noqa: BLE001 —— 东财节点随机断连，退避重试
            logger.warning("筹码K线 %s 第%d次失败: %s", code, attempt + 1, e)
            time.sleep(0.5 * (2**attempt))
    if payload is None:
        _mark_cooldown(code, now)
        return None

    data = (payload.get("data") or {})
    raw = data.get("klines")
    if not isinstance(raw, list) or len(raw) < 30:
        _mark_cooldown(code, now)
        return None

    klines = [row.split(",") for row in raw]
    dates: list[str] = []
    profit: list[float] = []
    avgc: list[float] = []
    lo90: list[float] = []
    hi90: list[float] = []
    conc: list[float] = []
    # 只算最近 90 日（窗口 120 已覆盖），减少 CPU
    start_idx = max(len(klines) - 90, _CYQ_WINDOW - 1)
    for i in range(start_idx, len(klines)):
        row = klines[i]
        s = _cyq_summary(klines, i)
        if s is None:
            continue
        dates.append(str(row[0])[:10])
        profit.append(s["profit_ratio"])
        avgc.append(s["avg_cost"])
        lo90.append(s["cost_90_low"])
        hi90.append(s["cost_90_high"])
        conc.append(s["concentration_90"])
    if not dates:
        _mark_cooldown(code, now)
        return None

    _clear_cooldown(code)
    return {
        "code": code,
        "dates": dates,
        "profit_ratio": profit,
        "avg_cost": avgc,
        "cost_90_low": lo90,
        "cost_90_high": hi90,
        "concentration_90": conc,
        "close": float(klines[-1][2]),
    }


def get_chip_distribution(code: str) -> dict[str, Any] | None:
    """获取单只筹码分布序列（带每日缓存 + 失败冷却）。失败/冷却期返回 None。"""
    now = time.time()
    with _lock:
        hit = _cache.get(code)
        if hit:
            cached_at, cached_val = hit
            ttl = _CHIP_TTL_OK if cached_val is not None else _CHIP_TTL_FAIL
            if now - cached_at < ttl:
                return cached_val

    if _in_cooldown(code, now):
        return None

    result = _fetch_chip_one(code)

    with _lock:
        if len(_cache) >= _CACHE_MAX:
            for k in sorted(_cache, key=lambda k: _cache[k][0])[: _CACHE_MAX // 2]:
                _cache.pop(k, None)
        _cache[code] = (now, result)
    return result


def get_chip_batch_async(codes: list[str]):
    """异步批量获取（route 层 await 调用）。失败返回 None 不抛。"""
    if not codes:
        return {}

    async def _one(code: str):
        return code, await asyncio.to_thread(get_chip_distribution, code)

    async def _run():
        pairs = await concurrency.gather_limited(
            [_one(c) for c in codes], concurrency.FETCH_CONCURRENCY
        )
        return dict(pairs)

    return _run()


def chip_status() -> dict[str, Any]:
    """诊断口：缓存与冷却状态。"""
    now = time.time()
    with _lock:
        ok = sum(1 for _, (t, v) in _cache.items() if v is not None and now - t < _CHIP_TTL_OK)
        fail = sum(1 for _, (t, v) in _cache.items() if v is None and now - t < _CHIP_TTL_FAIL)
        cooling = sum(1 for t in _cooldown.values() if t > now)
    return {"cached_ok": ok, "cached_fail": fail, "cooling": cooling}


# 供 detect 层取日线复用（历史换手率已补齐，形态判定用 data_service 的缓存）
_ = data_service  # 保持导入语义：detect 层会自行 import，这里仅文档化关联
