"""价格预警中心接口：规则 CRUD + 事件 + 评估触发（需登录）。"""
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.services import alert_service
from app.routes.portfolio import _require_user

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


class RuleCreate(BaseModel):
    code: str = Field(..., min_length=6, max_length=6)
    type: str  # stop_loss / breakdown / price_target
    threshold: float = Field(..., gt=0)
    name: str = ""
    note: str = ""


@router.get("/rules")
async def get_rules(user_id: str = Depends(_require_user)):
    return await alert_service.list_rules(user_id)


@router.post("/rules")
async def post_rule(req: RuleCreate, user_id: str = Depends(_require_user)):
    try:
        return await alert_service.add_rule(user_id, req.code, req.type, req.threshold, req.name, req.note)
    except ValueError as e:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/rules/{rule_id}")
async def del_rule(rule_id: int, user_id: str = Depends(_require_user)):
    ok = await alert_service.delete_rule(user_id, rule_id)
    if not ok:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="规则不存在")
    return {"ok": True}


@router.get("/events")
async def get_events(
    unread_only: bool = Query(False),
    limit: int = Query(50, le=200),
    user_id: str = Depends(_require_user),
):
    return await alert_service.list_events(user_id, unread_only=unread_only, limit=limit)


@router.get("/unread")
async def get_unread(user_id: str = Depends(_require_user)):
    return {"count": await alert_service.unread_count(user_id)}


@router.post("/read")
async def post_read(user_id: str = Depends(_require_user)):
    return {"updated": await alert_service.mark_read(user_id)}


@router.post("/read/partial")
async def post_read_partial(ids: list[int], user_id: str = Depends(_require_user)):
    return {"updated": await alert_service.mark_read(user_id, ids)}


@router.post("/evaluate")
async def post_evaluate(user_id: str = Depends(_require_user)):
    """前端盯盘轮询触发：评估当前用户规则并落库事件。"""
    return {"new_events": await alert_service.evaluate_for_user(user_id)}
