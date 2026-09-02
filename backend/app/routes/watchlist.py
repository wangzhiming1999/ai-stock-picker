"""自选股接口：添加/批量导入/列表涨跌看板/删除（需登录）。"""
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.services import supabase_store, watchlist_service

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


async def _require_user(authorization: str | None = Header(None)) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="请先登录")
    token = authorization.split(" ", 1)[1].strip()
    user = await supabase_store.get_user_by_token(token)
    if user is None:
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
    return user.id


class WatchAdd(BaseModel):
    code: str = Field(..., min_length=6, max_length=6)


class WatchImport(BaseModel):
    codes: list[str] = Field(..., max_length=100)


class WatchCheck(BaseModel):
    codes: list[str] = Field(..., max_length=50)


@router.get("")
async def get_watchlist(user_id: str = Depends(_require_user)):
    return await watchlist_service.list_watch(user_id)


@router.post("")
async def add_watch(req: WatchAdd, user_id: str = Depends(_require_user)):
    try:
        return await watchlist_service.add_watch(user_id, req.code)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/import")
async def import_watch(req: WatchImport, user_id: str = Depends(_require_user)):
    return await watchlist_service.import_watch(user_id, req.codes)


@router.post("/check")
async def check_watch(req: WatchCheck, user_id: str = Depends(_require_user)):
    """查询哪些代码已在自选（星标态用）。"""
    return await watchlist_service.is_watched(user_id, req.codes)


@router.delete("/{watch_id}")
async def remove_watch(watch_id: int, user_id: str = Depends(_require_user)):
    ok = await watchlist_service.remove_watch(user_id, watch_id)
    if not ok:
        raise HTTPException(status_code=404, detail="自选不存在")
    return {"ok": True}
