"""今日作战简报接口。"""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from app.services import briefing_service, supabase_store

router = APIRouter(prefix="/api/briefing", tags=["briefing"])


async def _optional_user(authorization: str | None = Header(None)) -> str | None:
    """可选登录：带有效 token 返回 user_id，否则 None（仍可看公开部分）。"""
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    try:
        user = await supabase_store.get_user_by_token(token)
    except Exception:
        return None
    return user.id if user else None


@router.get("/today")
async def briefing_today(authorization: str | None = Header(None)) -> dict:
    """今日作战简报：大盘方向 + 早盘买什么 + 尾盘怎么操作。

    未登录返回公开部分（大盘 + 早盘关注），tail 标记 need_login。
    """
    try:
        user_id = await _optional_user(authorization)
        return await briefing_service.build_today(user_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"生成简报失败: {e}")
