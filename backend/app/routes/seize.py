"""封板雷达路由：抢封板观察层的实时接口。

* ``GET /api/seize/radar`` —— 刚封板 / 回封候选 / 炸板预警，15 秒内存缓存，盘中高频轮询友好。
  数据源为东财 push2ex 涨停池 + 炸板池（与 ``limitup`` 同源、单次请求、零额外风控风险），
  因此不接 ``spotGuard`` 那套冷却闸门。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

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


@router.get("/history")
async def history(days: int = Query(14, ge=1, le=60)) -> dict:
    """收益追踪：近 N 个自然日的落库记录 + 已结算汇总。

    ⚠️ 会顺带触发结算：为「已判定未结算」的行逐只拉一次日 K（腾讯，单次上限 30 只，
    写入即固化），带 30 分钟节流 —— 不会放大行情请求。
    落库未启用（v15 迁移未跑 / Supabase 未配置）时返回 ``enabled:false``，
    前端降级隐藏，不报错。
    """
    return await seize_service.get_history_log(days=days)


@router.get("/reseal-backtest")
async def reseal_backtest(
    days: int = Query(15, ge=2, le=15),
    force: bool = False,
) -> dict:
    """回封策略历史回测（炸板池收在涨停 ±3% → 次日开盘卖出）。

    ⚠️ **行情源高风险端点**：首跑会为每只候选逐只拉一次日 K（上限 200 只）。
    结果缓存 6 小时；``force=true`` 穿透缓存，请仅在确认行情源状态正常时使用。
    数据窗口受 push2ex 回溯限制（约 15 个交易日），口径近似声明见返回体 ``note``。
    """
    return await seize_service.reseal_backtest(days=days, force=force)


@router.get("/sealed-backtest")
async def sealed_backtest(
    days: int = Query(15, ge=2, le=15),
    force: bool = False,
) -> dict:
    """刚封板档雷达口径回测（盘中首封 09:30-14:30，涨停价买入 → D+1 开盘卖）。

    ⚠️ 与 reseal-backtest 同级风险：逐只拉日 K（上限 200 只），结果缓存 6 小时。
    母口径为 limitup_premium；此处只做「雷达实际能捕捉子集」的切分。
    """
    return await seize_service.sealed_radar_backtest(days=days, force=force)
