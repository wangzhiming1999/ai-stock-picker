"""历史记录接口：查询分析批次与结果。

支持两种存储：配置 Supabase 后走 Postgres（按用户隔离），否则回退本地 SQLite。
"""
from fastapi import APIRouter, Depends, HTTPException, Request

from app import store
from app.services import supabase_store

router = APIRouter(prefix="/api/history", tags=["history"])


async def _resolve_user(request: Request) -> str | None:
    """从 Authorization: Bearer <jwt> 解析用户 id（未带 token 返回 None）。"""
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    token = auth.split(" ", 1)[1].strip()
    user = await supabase_store.get_user_by_token(token)
    return user.id if user else None


@router.get("/batches")
async def get_batches(request: Request, limit: int = 20):
    """最近的分析批次列表。"""
    if supabase_store.is_configured():
        user_id = await _resolve_user(request)
        return await supabase_store.list_batches(user_id, limit)
    return store.list_batches(limit)


@router.get("/batches/{batch_id}")
async def get_batch_detail(request: Request, batch_id: int):
    """批次详情（含全部个股结果）。"""
    if supabase_store.is_configured():
        user_id = await _resolve_user(request)
        batch = await supabase_store.get_batch(batch_id, user_id)
        if batch is None:
            raise HTTPException(status_code=404, detail="批次不存在或无权限")
        return batch
    batch = store.get_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="批次不存在")
    return batch
