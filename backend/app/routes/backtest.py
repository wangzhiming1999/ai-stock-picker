"""策略回测接口。"""
import asyncio
import datetime as dt

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.backtest_service import BacktestParams, STRATEGY_BACKTEST_POOL, run_backtest
from app.services import (
    pattern_service,
    recommend_calibration_service,
    recommend_history_replay_service,
    supabase_store,
    tactic_backtest_service,
)

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
    valid = {"momentum", "trend", "value", "volume", "all", "quality_momentum"}
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
    # 缓存键必须包含完整参数（codes/initial_capital 不同结果不同），避免串结果
    codes_sig = ",".join(sorted(req.codes)) if req.codes else "default"
    cache_key = (
        f"{req.strategy}|{req.start_date}|{req.end_date}|{req.top_n}"
        f"|{req.rebalance_days}|{req.initial_capital}|{codes_sig}"
    )

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
            await _save_backtest(cache_key, params.__dict__, result)
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


async def _save_backtest(cache_key: str, params: dict, result: dict) -> None:
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
        "params": params,
        "result": result,
    }
    if existing.data:
        await sb.table("backtest_results").update(payload).eq("id", existing.data[0]["id"]).execute()
    else:
        await sb.table("backtest_results").insert(payload).execute()


@router.get("/pool")
async def backtest_pool():
    """策略回测默认股票池（18 只）。

    形态回测用的是另一个池（`tactic_backtest_service.TACTIC_BACKTEST_POOL`，42 只），
    两者不通用 —— 历史上同名 DEFAULT_POOL，别再把这里当成通用池。
    """
    return {"codes": STRATEGY_BACKTEST_POOL, "count": len(STRATEGY_BACKTEST_POOL)}


class TacticBacktestRequest(BaseModel):
    """实战形态回测请求"""
    tactic: str | None = Field(None, description="技巧 key（见 /api/market/tactics），不传=全部可回测技巧")
    codes: list[str] | None = Field(None, description="股票池，缺省用形态回测默认池（42 只）")
    horizon_days: int = Field(10, ge=1, le=30, description="持有期（交易日）")
    eval_bars: int = Field(250, ge=60, le=400, description="每只票参与评估的最近交易日数")


class RecommendHistoryCalibrationRequest(BaseModel):
    codes: list[str] | None = Field(
        None,
        min_length=1,
        max_length=30,
        description="历史校验股票池（最多30只），缺省使用策略回测池",
    )
    eval_days: int = Field(120, ge=40, le=300, description="每只股票最近评估交易日数")
    top_n: int = Field(10, ge=1, le=20, description="每天模拟选择数量")
    min_train_days: int = Field(20, ge=10, le=120, description="首个训练窗口交易日数")
    validation_days: int = Field(5, ge=2, le=30, description="每折样本外验证交易日数")


class RecommendCalibrationRequest(BaseModel):
    min_train_days: int = Field(20, ge=10, le=120, description="首个训练窗口交易日数")
    validation_days: int = Field(5, ge=2, le=30, description="每折样本外验证交易日数")
    top_n: int = Field(10, ge=1, le=20, description="每个交易日模拟选取数量")
    min_train_selections: int = Field(30, ge=20, le=1000, description="每折训练期最少有效记录")
    min_oos_selections: int = Field(60, ge=30, le=1000, description="允许复核所需最少样本外记录")


@router.post("/recommend-calibration")
async def recommend_calibration_endpoint(req: RecommendCalibrationRequest):
    """用生产推荐原始分数做扩展窗口训练和下一窗口样本外验证。

    结果只提供参数复核建议，不自动替换线上参数。数据库需先执行 v17 迁移；迁移后
    新增样本才具备原始四策略分，旧记录不会被伪造补值。
    """
    if not supabase_store.is_configured():
        return {
            "status": "storage_not_configured",
            "deployment_eligible": False,
            "deployment_reason": "Supabase 未配置，无法读取生产结算样本",
        }
    try:
        sb = await supabase_store.get_service_client()
        response = (
            await sb.table("daily_recommendations")
            .select("rec_date,code,strategy_scores,excess_return,execution_status,source")
            .not_.is_("settled_at", None)
            .execute()
        )
    except Exception as error:
        if "strategy_scores" in str(error):
            return {
                "status": "migration_required",
                "deployment_eligible": False,
                "deployment_reason": "请先执行 backend/supabase-schema-v17.sql",
            }
        raise HTTPException(status_code=502, detail=f"推荐校准样本读取失败: {error}")

    samples = recommend_calibration_service.prepare_calibration_samples(response.data or [])
    result = recommend_calibration_service.calibrate_walk_forward(
        samples,
        min_train_days=req.min_train_days,
        validation_days=req.validation_days,
        top_n=req.top_n,
        min_train_selections=req.min_train_selections,
        min_oos_selections=req.min_oos_selections,
    )
    result["source_rows"] = len(response.data or [])
    result["caliber"] = "按生产全量达标候选原始四策略分重排；T+1 已触发记录；收益口径为扣费后相对沪深300超额"
    return result


@router.post("/recommend-history-calibration")
async def recommend_history_calibration_endpoint(req: RecommendHistoryCalibrationRequest):
    """拉取历史日线进行无未来函数的技术因子研究校验。"""
    result = await asyncio.to_thread(
        recommend_history_replay_service.run_historical_calibration,
        codes=req.codes,
        eval_days=req.eval_days,
        top_n=req.top_n,
        min_train_days=req.min_train_days,
        validation_days=req.validation_days,
    )
    # 历史日线无法还原当时的完整基本面截面，任何内部结果都不得直接部署。
    result["deployment_eligible"] = False
    result["validation_scope"] = "research_only_technical_factors"
    return result


@router.get("/recommend-snapshot-readiness")
async def recommend_snapshot_readiness_endpoint():
    """Report whether production point-in-time features are mature enough for replay."""
    if not supabase_store.is_configured():
        return {
            "ready_for_full_factor_replay": False,
            "status": "storage_not_configured",
            "blockers": ["storage_not_configured"],
        }
    try:
        sb = await supabase_store.get_service_client()
        response = (
            await sb.table("daily_recommendations")
            .select("rec_date,source,settled_at,feature_snapshot")
            .execute()
        )
    except Exception as error:
        if "feature_snapshot" in str(error):
            return {
                "ready_for_full_factor_replay": False,
                "status": "migration_required",
                "blockers": ["feature_snapshot_column_missing"],
                "migration": "backend/supabase-schema-v18.sql",
            }
        raise HTTPException(status_code=502, detail=f"点时快照覆盖率读取失败: {error}")
    result = recommend_calibration_service.assess_feature_snapshot_readiness(response.data or [])
    result["status"] = "ready" if result["ready_for_full_factor_replay"] else "accumulating"
    return result


@router.post("/tactic")
async def tactic_backtest_endpoint(req: TacticBacktestRequest):
    """实战形态历史回测：walk-forward 验证技巧表现，并与同区间基准对比。

    结论仅供参考：免费数据源只有日线历史，分时背离无法回测；天量见天价的换手率条件
    已在回测中生效（历史换手率来自腾讯日线），个别时点缺值会在该条结果的 note 里报出。
    命中样本过少时返回 `insufficient_data`，不给结论。
    """
    keys: list[str] | None = None
    if req.tactic:
        if req.tactic not in pattern_service.TACTIC_MAP:
            raise HTTPException(
                status_code=400,
                detail=f"未知技巧 {req.tactic}，可选: {list(pattern_service.TACTIC_MAP)}",
            )
        keys = [req.tactic]
    # 回测结果按「数据日 + 参数」缓存：日线一天只新增一根，同参数重复跑没有意义
    data_day = dt.date.today().isoformat()
    try:
        from app.services import trade_calendar_service

        data_day = (await trade_calendar_service.last_trading_day()).isoformat()
    except Exception:
        pass
    pool_sig = ",".join(sorted(req.codes)) if req.codes else "default"
    cache_key = f"tactic|{req.tactic or 'all'}|{data_day}|{req.horizon_days}|{req.eval_bars}|{pool_sig}"
    cached = await _load_backtest(cache_key)
    if cached:
        return cached

    try:
        result = await tactic_backtest_service.evaluate(
            codes=req.codes,
            keys=keys,
            horizon=req.horizon_days,
            eval_bars=req.eval_bars,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"形态回测失败: {e}")

    if "error" not in result:
        try:
            await _save_backtest(
                cache_key,
                {
                    "tactic": req.tactic,
                    "codes": req.codes,
                    "horizon_days": req.horizon_days,
                    "eval_bars": req.eval_bars,
                    "data_day": data_day,
                },
                result,
            )
        except Exception as e:
            print(f"[backtest] 形态回测缓存写入失败: {e}")
    return result
