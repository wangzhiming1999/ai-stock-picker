"""持仓接口：用户持仓 CRUD + 风险等级 + 持仓建议 + 批量导入（需登录）。"""
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from app.services import import_service, portfolio_service, supabase_store

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


async def _require_user(authorization: str | None = Header(None)) -> str:
    """从 Authorization Bearer JWT 解析用户 id，未登录抛 401。"""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="请先登录")
    token = authorization.split(" ", 1)[1].strip()
    user = await supabase_store.get_user_by_token(token)
    if user is None:
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
    return user.id


class ProfileRequest(BaseModel):
    risk_level: str | None = None
    total_capital: float | None = Field(None, gt=0)


class HoldingCreate(BaseModel):
    code: str = Field(..., min_length=6, max_length=6)
    cost_price: float = Field(..., gt=0)
    shares: int = Field(..., gt=0)
    buy_date: str | None = None
    note: str = ""


class HoldingUpdate(BaseModel):
    cost_price: float | None = Field(None, gt=0)
    shares: int | None = Field(None, gt=0)
    buy_date: str | None = None
    note: str | None = None


class BatchHoldingItem(BaseModel):
    code: str = Field(..., min_length=6, max_length=6)
    name: str = ""
    cost_price: float = Field(..., gt=0)
    shares: int = Field(..., gt=0)
    buy_date: str | None = None
    note: str = ""


class BatchHoldingsRequest(BaseModel):
    items: list[BatchHoldingItem] = Field(..., min_length=1, max_length=50)


class ImportParseRequest(BaseModel):
    """持仓导入解析：二选一传 text（粘贴文本）或 image_base64（截图）。"""
    text: str | None = None
    image_base64: str | None = None


@router.get("/profile")
async def get_profile(user_id: str = Depends(_require_user)):
    return await portfolio_service.get_profile(user_id)


@router.put("/profile")
async def put_profile(req: ProfileRequest, user_id: str = Depends(_require_user)):
    try:
        return await portfolio_service.set_profile(
            user_id, risk_level=req.risk_level, total_capital=req.total_capital
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/holdings")
async def get_holdings(user_id: str = Depends(_require_user)):
    return await portfolio_service.list_holdings(user_id)


@router.post("/holdings")
async def post_holding(req: HoldingCreate, user_id: str = Depends(_require_user)):
    try:
        item = await portfolio_service.add_holding(
            user_id, req.code, req.cost_price, req.shares, req.buy_date, req.note
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return item


@router.post("/holdings/batch")
async def post_holdings_batch(req: BatchHoldingsRequest, user_id: str = Depends(_require_user)):
    """批量导入持仓（同代码更新）。"""
    try:
        return await portfolio_service.add_holdings_batch(user_id, [i.model_dump() for i in req.items])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/holdings/{holding_id}")
async def put_holding(holding_id: int, req: HoldingUpdate, user_id: str = Depends(_require_user)):
    try:
        return await portfolio_service.update_holding(
            user_id, holding_id, **req.model_dump(exclude_none=True)
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/holdings/{holding_id}")
async def delete_holding(holding_id: int, user_id: str = Depends(_require_user)):
    ok = await portfolio_service.remove_holding(user_id, holding_id)
    if not ok:
        raise HTTPException(status_code=404, detail="持仓不存在")
    return {"ok": True}


@router.get("/advice")
async def get_advice(user_id: str = Depends(_require_user)):
    try:
        return await portfolio_service.get_portfolio_advice(user_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"持仓建议生成失败: {type(e).__name__}: {e}")


@router.post("/import/parse")
async def parse_import(req: ImportParseRequest, user_id: str = Depends(_require_user)):
    """解析持仓导入内容（粘贴文本 / 截图），返回候选列表供前端预览确认。不落库。"""
    try:
        if req.image_base64:
            items, warnings = await import_service.parse_holdings_image(req.image_base64)
        elif req.text and req.text.strip():
            items, warnings = await import_service.parse_holdings_text(req.text)
        else:
            raise HTTPException(status_code=400, detail="请提供截图或粘贴持仓文本")
        items = await import_service.enrich_names(items)
        return {"items": items, "warnings": warnings}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"解析失败: {type(e).__name__}: {e}")
