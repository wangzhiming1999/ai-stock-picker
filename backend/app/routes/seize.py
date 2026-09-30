"""封板雷达路由：抢封板观察层的实时接口。

* ``GET /api/seize/radar`` —— 刚封板 / 回封候选 / 炸板预警，15 秒内存缓存，盘中高频轮询友好。
  数据源为东财 push2ex 涨停池 + 炸板池（与 ``limitup`` 同源、单次请求、零额外风控风险），
  因此不接 ``spotGuard`` 那套冷却闸门。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.services import seize_service

router = APIRouter(prefix="/api/seize", tags=["seize"])


@router.get("/radar")
async def radar(force: bool = False) -> dict:
    """封板雷达实时数据。

    ``force=true`` 穿透 15 秒内存缓存，重新拉取涨停池 + 炸板池。前端默认走缓存即可，
    盘中轮询频率已受后端缓存约束，不会放大行情请求。
    """
    try:
        return await seize_service.get_radar(force=force)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
