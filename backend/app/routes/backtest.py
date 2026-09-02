"""策略回测接口。"""
import asyncio
import datetime as dt

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.backtest_service import BacktestParams, DEFAULT_POOL, run_backtest
from app.services import supabase_store

router = APIRouter(prefix="/api/backtest", tags=["backtest"])


class BacktestRequest(BaseModel):
    strategy: str = Field("momentum", description="策略: momentum/trend/value/volume/all")
    codes: list[str] | None = Field(None, description="股票池，缺省用默认池")
    start_date: str = Field("2025-01-01", description="开始日期")
    end_date: str = Field("", description="结束日期，缺省今天")
    top_n: int = Field(5, ge=1, le=20, description="每期持有数量")
    rebalance_days: int = Field(5, ge=1, le=30, description="调仓周期（交易日）")
    initial_capital: float = Field(100000, gt=0, description="初始资金")


@router.post("/run")
async def backtest_run(req: BacktestRequest):
    """运行策略回测（结果持久化，同参数直接复用）。"""
    valid = {"momentum", "trend", "value", "volume", "all"}
    if req.strategy not in valid:
        raise HTTPException(status_code=400, detail=f"未知策略 {req.strategy}，可选: {valid}")
    params = BacktestParams(
        strategy=req.strategy,
        codes=req.codes,
        start_date=req.start_date,
        end_date=req.end_date,
        top_n=req.top_n,
        rebalance_days=req.rebalance_days,
        initial_capital=req.initial_capital,
    )
    cache_key = f"{req.strategy}|{req.start_date}|{req.end_date}|{req.top_n}|{req.rebalance_days}"

    # 1. 数据库缓存
    cached = await _load_backtest(cache_key)
    if cached:
        return cached

    # 2. 运行回测
    try:
        result = await asyncio.to_thread(run_backtest, params)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"回测失败: {e}")

    # 3. 写缓存
    if "error" not in result:
        try:
            await _save_backtest(cache_key, params, result)
        except Exception as e:
            print(f"[backtest] 缓存写入失败: {e}")
    return result


async def _load_backtest(cache_key: str) -> dict | None:
    if not supabase_store.is_configured():
        return None
    try:
        sb = await supabase_store.get_service_client()
        res = (
            await sb.table("backtest_results")
            .select("result")
            .eq("cache_key", cache_key)
            .limit(1)
            .execute()
        )
        if res.data:
            return res.data[0]["result"]
    except Exception as e:
        print(f"[backtest] 数据库读取失败: {e}")
    return None


async def _save_backtest(cache_key: str, params: BacktestParams, result: dict) -> None:
    if not supabase_store.is_configured():
        return
    sb = await supabase_store.get_service_client()
    existing = (
        await sb.table("backtest_results")
        .select("id")
        .eq("cache_key", cache_key)
        .limit(1)
        .execute()
    )
    payload = {
        "cache_key": cache_key,
        "params": params.__dict__,
        "result": result,
    }
    if existing.data:
        await sb.table("backtest_results").update(payload).eq("id", existing.data[0]["id"]).execute()
    else:
        await sb.table("backtest_results").insert(payload).execute()


@router.get("/pool")
async def backtest_pool():
    """默认股票池。"""
    return {"codes": DEFAULT_POOL, "count": len(DEFAULT_POOL)}
