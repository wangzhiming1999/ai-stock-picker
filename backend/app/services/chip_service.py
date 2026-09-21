"""筹码分布（CYQ）数据服务。

数据源：东财 `ak.stock_cyq_em(code, adjust="")` —— 比行情源更脆弱（间歇性
ProxyError），因此套三层保护：
1. akshare_guard 进程级串行（akshare JS 运行时不可并发）；
2. 每日级 TTL 进程内缓存（筹码峰形态以日级变化为主，日内刷新无意义）；
3. 失败冷却（复用 market_source_state 模式思路，进程内冷却表），冷却期内
   直接返回缓存/None，绝不连打。

批量逐只走 concurrency.gather_limited（配额 8）。
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any

import akshare as ak

from app.services import akshare_guard, concurrency

logger = logging.getLogger(__name__)

# 筹码数据日内基本不变（每天收盘后更新一次），缓存一整个交易日
_CHIP_TTL_OK = 6 * 3600
# 失败短缓存：冷却期内不再真拉
_CHIP_TTL_FAIL = 30 * 60
# 失败冷却：东财 ProxyError 后至少隔这么久才允许下一次真拉
_COOLDOWN_SECS = 15 * 60
# 进程内缓存上限（42 只池 + 富余），超出淘汰最旧一半
_CACHE_MAX = 200

_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}
_lock = threading.Lock()
# 冷却表：code -> 失败时间戳（进程级；serverless 多实例各自冷却，可接受）
_cooldown: dict[str, float] = {}


def _in_cooldown(code: str, now: float) -> bool:
    until = _cooldown.get(code)
    return until is not None and now < until


def _mark_cooldown(code: str, now: float) -> None:
    _cooldown[code] = now + _COOLDOWN_SECS
    # 冷却表只增不减会缓慢泄漏，清掉已过期的
    expired = [c for c, t in _cooldown.items() if t <= now]
    for c in expired:
        _cooldown.pop(c, None)


def _clear_cooldown(code: str) -> None:
    _cooldown.pop(code, None)


def _fetch_chip_one(code: str, now: float) -> dict[str, Any] | None:
    """真拉单只筹码分布，解析为 {dates, profit_ratio, avg_cost, cost_90_low/high, concentration_90}。

    东财 stock_cyq_em 返回列（实测 1.16.94）：
    日期 / 获利比例 / 平均成本 / 90成本-低 / 90成本-高 / 90集中度 /
    70成本-低 / 70成本-高 / 70集中度，90 行（近 90 个交易日）。
    """
    try:
        frame = akshare_guard.call(ak.stock_cyq_em, code, adjust="")
        if frame is None or frame.empty:
            raise ValueError("empty frame")
        cols = list(frame.columns)
        need = ["日期", "获利比例", "平均成本", "90成本-低", "90成本-高", "90集中度"]
        if not all(c in cols for c in need):
            raise ValueError(f"unexpected columns: {cols}")

        def _col(name: str) -> list:
            return frame[name].tolist()

        dates = [str(d)[:10] for d in _col("日期")]
        data = {
            "code": code,
            "dates": dates,
            "profit_ratio": [float(x) for x in _col("获利比例")],
            "avg_cost": [float(x) for x in _col("平均成本")],
            "cost_90_low": [float(x) for x in _col("90成本-低")],
            "cost_90_high": [float(x) for x in _col("90成本-高")],
            "concentration_90": [float(x) for x in _col("90集中度")],
        }
        _clear_cooldown(code)
        return data
    except Exception as e:  # noqa: BLE001 —— 东财接口 flaky，任何异常一律降级
        logger.warning("获取 %s 筹码分布失败: %s", code, e)
        _mark_cooldown(code, now)
        return None


def get_chip_distribution(code: str) -> dict[str, Any] | None:
    """获取单只筹码分布（带每日缓存 + 失败冷却）。失败/冷却期返回 None。"""
    now = time.time()
    with _lock:
        hit = _cache.get(code)
        if hit:
            cached_at, cached_val = hit
            ttl = _CHIP_TTL_OK if cached_val is not None else _CHIP_TTL_FAIL
            if now - cached_at < ttl:
                return cached_val

    if _in_cooldown(code, now):
        # 冷却期内不真拉：若无可用缓存则返回 None
        return None

    result = _fetch_chip_one(code, now)

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
        # akshare 非线程安全，走 to_thread + akshare_guard 串行锁
        return code, await asyncio.to_thread(get_chip_distribution, code)

    async def _run():
        pairs = await concurrency.gather_limited(
            [_one(c) for c in codes], concurrency.FETCH_CONCURRENCY
        )
        return dict(pairs)

    return _run()


def chip_status() -> dict[str, Any]:
    """诊断口：缓存与冷却状态（供 spot-status 类端点参考）。"""
    now = time.time()
    with _lock:
        ok = sum(1 for _, (t, v) in _cache.items() if v is not None and now - t < _CHIP_TTL_OK)
        fail = sum(1 for _, (t, v) in _cache.items() if v is None and now - t < _CHIP_TTL_FAIL)
        cooling = sum(1 for t in _cooldown.values() if t > now)
    return {"cached_ok": ok, "cached_fail": fail, "cooling": cooling}
