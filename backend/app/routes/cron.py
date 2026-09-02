"""定时任务路由：Vercel Cron 触发每日收盘结算。"""
import os

from fastapi import APIRouter, HTTPException, Request

from app.services import winrate_service

router = APIRouter(prefix="/api/cron", tags=["cron"])


@router.post("/daily")
async def daily_cron(request: Request):
    """每日收盘定时任务：结算预测 + 结算推荐 + 刷新胜率快照。

    Vercel Cron 触发，校验 Authorization Bearer 与 CRON_SECRET 一致。
    """
    expected = os.getenv("CRON_SECRET", "")
    if not expected:
        raise HTTPException(status_code=503, detail="CRON_SECRET 未配置")
    auth = request.headers.get("authorization", "")
    provided = auth.removeprefix("Bearer ").strip() if auth.startswith("Bearer ") else ""
    if provided != expected:
        raise HTTPException(status_code=401, detail="未授权")
    try:
        return await winrate_service.run_daily_cron()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"定时任务失败: {e}")
