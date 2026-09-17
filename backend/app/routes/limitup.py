"""连板梯队与晋级率接口。

两个端点：

* ``GET /api/limitup/snapshot`` —— 当日连板全景（情绪 / 梯队 / 板块 / 个股位置），60s 内存缓存；
* ``GET /api/limitup/relay`` —— 历史 N 连板 → 次日晋级率，默认取满接口回溯窗口。

⚠️ 两个端点返回的 ``evidence.actionable`` 恒为 ``false``。连板接力只在「能否继续封板」
这个中间指标上有正向线索，缺少收益口径（涨停池拿不到次日成交价），因此按项目证据闸门
（``tactic_evidence``）只能停在「初步」。前端**不得**把这里的任何字段渲染成买点或建议。

数据源是东财 ``push2ex`` 涨停板池 —— 与 ``spot_service`` 使用的 ``push2`` 全市场快照
是不同域名/不同业务端点，push2 被风控时本模块不受影响，因此这里**不接**快照那套冷却机制。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.services import limitup_service

router = APIRouter(prefix="/api/limitup", tags=["limitup"])


@router.get("/snapshot")
async def snapshot(force: bool = False) -> dict:
    """当日连板全景。

    ``force=true`` 穿透 60 秒内存缓存。涨停池是单次请求，代价远低于全市场快照，
    但盘中也没必要高频穿透，前端默认走缓存即可。
    """
    try:
        return await limitup_service.get_snapshot(force=force)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/relay")
async def relay(
    days: int = Query(limitup_service.MAX_RELAY_DAYS, ge=2, le=40),
    force: bool = False,
) -> dict:
    """连板晋级率回溯。

    默认取满接口回溯窗口（约 15 个交易日）。传更大的 ``days`` 不会扩大样本 ——
    更早的日期接口返回空池，会被识别为「无数据」并排除，这一点在返回体的
    ``empty_dates`` / ``data_window`` 里可自查。
    """
    try:
        return await limitup_service.relay_backtest(days=days, force=force)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
