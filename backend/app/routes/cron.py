"""定时任务路由：Vercel Cron 触发每日收盘结算。"""
import os

from fastapi import APIRouter, HTTPException, Request

from app.services import alert_service, quad_service, winrate_service

router = APIRouter(prefix="/api/cron", tags=["cron"])


def _authorize(request: Request) -> None:
    """校验 CRON_SECRET，未配置或失败抛异常。"""
    expected = os.getenv("CRON_SECRET", "")
    if not expected:
        raise HTTPException(status_code=503, detail="CRON_SECRET 未配置")
    auth = request.headers.get("authorization", "")
    provided = auth.removeprefix("Bearer ").strip() if auth.startswith("Bearer ") else ""
    if provided != expected:
        raise HTTPException(status_code=401, detail="未授权")


@router.post("/daily")
async def daily_cron(request: Request):
    """每日收盘定时任务：结算预测 + 结算推荐 + 刷新胜率快照。

    Vercel Cron 触发，校验 Authorization Bearer 与 CRON_SECRET 一致。
    """
    _authorize(request)
    try:
        return await winrate_service.run_daily_cron()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"定时任务失败: {e}")


@router.post("/quad")
async def quad_cron(request: Request):
    """收盘后预生成当日四维牛股榜，让用户白天访问秒回。

    在每日收盘（北京 16:05）由 Vercel Cron 触发。
    """
    _authorize(request)
    try:
        result = await quad_service.generate_quad_rankings(force_refresh=True)
        return {"ok": True, "date": result["date"], "items": len(result["items"]), "pool": result["pool_size"]}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"四维牛股榜预热失败: {e}")


@router.post("/alert")
async def alert_cron(request: Request):
    """兜底评估全部用户预警规则（用户关机时也能记事件历史）。

    频率受 Vercel Cron 套餐限制，高频实时性由前端盯盘轮询的 /api/alerts/evaluate 保证。
    """
    _authorize(request)
    try:
        return await alert_service.evaluate_all()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"预警评估失败: {e}")
