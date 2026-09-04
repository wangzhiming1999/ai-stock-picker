"""定时任务路由：Vercel Cron 触发每日收盘结算。"""
import os

from fastapi import APIRouter, HTTPException, Request

from app.services import alert_service, quad_service, sim_service, winrate_service

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
    """每日收盘定时任务：结算预测 + 结算推荐 + 刷新胜率快照 + 预警兜底评估。

    Vercel Cron 触发，校验 Authorization Bearer 与 CRON_SECRET 一致。
    V6 预警兜底评估合并进每日任务（Hobby 计划 cron 数量受限，高频实时性由前端盯盘轮询保证）。
    """
    _authorize(request)
    try:
        result = await winrate_service.run_daily_cron()
        # V6 预警兜底：合并进每日结算，避免超出 Vercel Hobby cron 数量限制
        try:
            result["alert_events"] = await alert_service.evaluate_all()
        except Exception as ae:  # 预警评估失败不影响胜率结算结果
            print(f"[cron] alert evaluate_all failed: {ae}")
            result["alert_events"] = None
        # V5 模拟盘：为所有有模拟流水的用户写当日净值快照（表未建时静默失败）
        try:
            result["sim_snapshots"] = await sim_service.snapshot_all_users()
        except Exception as se:
            print(f"[cron] sim snapshot failed: {se}")
            result["sim_snapshots"] = None
        return result
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
