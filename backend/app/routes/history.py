"""历史记录接口：查询分析批次与结果。"""
from fastapi import APIRouter, HTTPException

from app import store

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("/batches")
async def get_batches(limit: int = 20):
    """最近的分析批次列表。"""
    return store.list_batches(limit)


@router.get("/batches/{batch_id}")
async def get_batch_detail(batch_id: int):
    """批次详情（含全部个股结果）。"""
    batch = store.get_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="批次不存在")
    return batch
