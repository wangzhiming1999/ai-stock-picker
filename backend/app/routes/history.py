"""历史记录接口：查询分析批次与结果。

支持两种存储：配置 Supabase 后走 Postgres（按用户隔离），否则回退本地 SQLite。
"""
from fastapi import APIRouter, Depends, Header, HTTPException

from app import store
from app.services import supabase_store
from app.routes.portfolio import _require_user

router = APIRouter(prefix="/api/history", tags=["history"])


async def _history_user(authorization: str | None = Header(None)) -> str | None:
    """Supabase 生产存储强制登录；本地 SQLite 降级模式保持可用。"""
    if not supabase_store.is_configured():
        return None
    return await _require_user(authorization)


@router.get("/batches")
async def get_batches(limit: int = 20, user_id: str | None = Depends(_history_user)):
    """最近的分析批次列表。"""
    if supabase_store.is_configured():
        return await supabase_store.list_batches(user_id, limit)
    return store.list_batches(limit)


@router.get("/batches/{batch_id}")
async def get_batch_detail(batch_id: int, user_id: str | None = Depends(_history_user)):
    """批次详情（含全部个股结果）。"""
    if supabase_store.is_configured():
        batch = await supabase_store.get_batch(batch_id, user_id)
        if batch is None:
            raise HTTPException(status_code=404, detail="批次不存在或无权限")
        return batch
    batch = store.get_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="批次不存在")
    return batch
