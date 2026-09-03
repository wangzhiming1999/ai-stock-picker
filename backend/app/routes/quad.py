"""四维牛股榜路由。"""
from fastapi import APIRouter, HTTPException

from app.services import quad_service

router = APIRouter(prefix="/api/market", tags=["quad"])


@router.get("/quad")
async def quad_rankings(refresh: bool = False):
    """四维牛股榜：基本面/技术面/资金面/消息面 四维优秀的 Top 10。

    refresh=true 时忽略当日缓存强制重算。
    """
    try:
        return await quad_service.get_quad_rankings(force_refresh=refresh)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"四维牛股榜生成失败: {e}")
