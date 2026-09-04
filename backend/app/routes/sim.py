"""模拟盘接口：账户 / 买卖 / 持仓 / 流水 / 收益 / 重置（需登录）。"""
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.services import sim_service, supabase_store

router = APIRouter(prefix="/api/sim", tags=["sim"])


async def _require_user(authorization: str | None = Header(None)) -> str:
    """从 Authorization Bearer JWT 解析用户 id，未登录抛 401。"""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="请先登录")
    token = authorization.split(" ", 1)[1].strip()
    user = await supabase_store.get_user_by_token(token)
    if user is None:
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
    return user.id


class InitRequest(BaseModel):
    total_capital: float | None = Field(None, gt=0)


class TradeRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=6)
    side: str = Field(..., pattern="^(buy|sell)$")
    shares: int = Field(..., gt=0)
    price: float | None = Field(None, gt=0)
    source: str = Field("manual", pattern="^(manual|briefing|recommend)$")
    related_reco_id: str | None = None
    note: str = ""


class ResetRequest(BaseModel):
    confirm: bool = Field(..., description="须显式传 true")


@router.get("/account")
async def get_account(user_id: str = Depends(_require_user)):
    return await sim_service.get_account(user_id)


@router.post("/account/init")
async def init_account(req: InitRequest, user_id: str = Depends(_require_user)):
    return await sim_service.init_account(user_id, req.total_capital)


@router.post("/trade")
async def trade(req: TradeRequest, user_id: str = Depends(_require_user)):
    try:
        if req.side == "buy":
            return await sim_service.buy(
                user_id, req.code, req.shares, req.price,
                source=req.source, related_reco_id=req.related_reco_id, note=req.note,
            )
        return await sim_service.sell(
            user_id, req.code, req.shares, req.price,
            source=req.source, related_reco_id=req.related_reco_id, note=req.note,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/positions")
async def get_positions(user_id: str = Depends(_require_user)):
    try:
        return await sim_service.list_positions(user_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"持仓查询失败: {type(e).__name__}: {e}")


@router.get("/trades")
async def get_trades(limit: int = 50, offset: int = 0, user_id: str = Depends(_require_user)):
    return await sim_service.list_trades(user_id, limit=min(max(limit, 1), 200), offset=max(offset, 0))


@router.get("/performance")
async def get_performance(user_id: str = Depends(_require_user)):
    return await sim_service.get_performance(user_id)


@router.post("/reset")
async def reset(req: ResetRequest, user_id: str = Depends(_require_user)):
    if not req.confirm:
        raise HTTPException(status_code=400, detail="请确认后重试（confirm=true）")
    return await sim_service.reset(user_id)
