"""模拟盘接口：账户 / 买卖 / 持仓 / 流水 / 收益 / 重置（需登录）。"""
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.services import agent_decision_service, sim_service, supabase_store

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
    source: str = Field("manual", pattern="^(manual|briefing|recommend|agent|limitup_relay)$")
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


# ---------- Agent 决策闭环（TradingAgents 执行闭环） ----------


class AdoptPlanRequest(BaseModel):
    """一键采纳 agent 交易计划（终审 approved/demoted 的 buy/add 才能采纳）。"""

    decision_id: int = Field(..., description="agent_decisions.id（来自深度分析返回的 agent_decision_id）")
    price: float | None = Field(None, gt=0, description="成交价；缺省取实时价")


class _NoService(RuntimeError):
    """Supabase 未配置 / agent_decisions 表未建 —— 前端据此提示而非 500。"""


async def _locate_decision(decision_id: int, user_id: str) -> dict:
    """定位并校验一条可采纳的决策行。任何不满足都抛 400。"""
    sb = await supabase_store.get_service_client()
    try:
        res = (
            await sb.table("agent_decisions")
            .select("*")
            .eq("id", int(decision_id))
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
    except Exception:
        # 表不存在（v9 迁移未执行）是最常见原因，单独给口径
        raise HTTPException(
            status_code=503,
            detail="Agent 决策记录表未启用（需执行 supabase-schema-v9.sql），请先在 Supabase 控制台执行迁移",
        )
    row = (res.data or [None])[0]
    if row is None:
        raise HTTPException(status_code=404, detail="未找到该决策记录（或不属于当前用户）")
    if row.get("status") == "adopted":
        raise HTTPException(status_code=400, detail="该计划已被采纳过，请勿重复建仓")
    if row.get("status") == "rejected":
        raise HTTPException(status_code=400, detail="终审否决的计划不可采纳")
    if row.get("action") not in ("buy", "add"):
        raise HTTPException(status_code=400, detail=f"动作「{row.get('action')}」不是建仓计划，无可执行内容")
    if row.get("verdict") not in ("approved", "demoted"):
        raise HTTPException(status_code=400, detail="仅终审通过（approved/demoted）的计划可采纳")
    return row


@router.post("/from-plan")
async def adopt_from_plan(req: AdoptPlanRequest, user_id: str = Depends(_require_user)):
    """按 agent 终审计划建仓模拟盘。

    仓位换算：final_position_pct × 账户 total_capital ÷ 入场价 → 向下取整手数。
    手数不足 1 手（100 股）时报错 —— 计划仓位太小，提示用户手动按整手调整。
    止损/目标不生成挂单（无条件单能力），只写进 note 供盯盘对照。
    """
    row = await _locate_decision(req.decision_id, user_id)

    profile = await sim_service._get_or_create_profile(user_id)
    capital = float(profile.get("total_capital") or 0)
    entry = float(row.get("entry_price") or 0)
    pct = float(row.get("position_pct") or 0)
    if capital <= 0:
        raise HTTPException(status_code=400, detail="模拟账户未初始化总资金，请先在模拟盘初始化")
    if entry <= 0 or pct <= 0:
        raise HTTPException(status_code=400, detail="计划缺少入场价或仓位，无法换算手数")

    budget = capital * pct / 100.0
    shares = int(budget / entry / 100) * 100
    if shares <= 0:
        need = int((budget / entry) * 100) / 100
        raise HTTPException(
            status_code=400,
            detail=f"计划仓位太小：按 {pct:.0f}% × ¥{capital:,.0f} ÷ {entry} 约需 {need:.2f} 手，不足 1 手。请手动按整手建仓",
        )

    stop = row.get("stop_price")
    target = row.get("target_price")
    note_parts = [f"agent计划#{req.decision_id}"]
    if stop:
        note_parts.append(f"止损{stop}")
    if target:
        note_parts.append(f"目标{target}")

    try:
        result = await sim_service.buy(
            user_id,
            row["code"],
            shares,
            req.price,
            source="agent",
            related_reco_id=str(req.decision_id),
            note="，".join(note_parts),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    trade_id = (result.get("trade") or {}).get("id")
    await agent_decision_service.adopt(req.decision_id, user_id=user_id, shares=shares, sim_trade_id=trade_id)

    # 采纳成功后落库失败不影响成交返回（对照行下次重试时由 adopt 幂等更新）
    return {
        "trade": result.get("trade"),
        "account": result.get("account"),
        "plan": {
            "decision_id": req.decision_id,
            "code": row["code"],
            "shares": shares,
            "budget": round(budget, 2),
            "position_pct": pct,
            "stop_price": stop,
            "target_price": target,
        },
    }


@router.get("/agent-decisions")
async def agent_decisions(
    limit: int = 30, offset: int = 0, user_id: str = Depends(_require_user)
):
    """当前用户的 agent 决策记录 + 闭环统计（口径 agent_plan 随数据下发）。"""
    try:
        sb = await supabase_store.get_service_client()
    except Exception:
        raise HTTPException(status_code=503, detail="Supabase 未配置")
    try:
        res = (
            await sb.table("agent_decisions")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .range(max(offset, 0), max(offset, 0) + min(max(limit, 1), 100) - 1)
            .execute()
        )
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Agent 决策记录表未启用（需执行 supabase-schema-v9.sql）",
        )
    stats = await agent_decision_service.stats(user_id)
    return {"decisions": res.data or [], "stats": stats}
