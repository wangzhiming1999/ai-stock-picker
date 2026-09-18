"""跌停池与「次日修复」接口。

两个端点：

* ``GET /api/limitdown/snapshot`` —— 当日跌停全景（情绪 / 连跌梯队 / 板块聚集 / 个股位置），60s 内存缓存；
* ``GET /api/limitdown/repair`` —— 跌停次日修复的**真实收益**回溯（集合竞价 / 收盘 / 盘中最高）。

⚠️ 两个端点返回的 ``evidence.actionable`` 恒为 ``false``，且 ``evidence.tier`` 为
``unsupported`` —— 这不是「还没跑」，而是**跑出来是负期望**（见 ``tactic_evidence``：
n=133、期望 −4.47%/次、胜率 4.5%）。前端**不得**把这里的任何字段渲染成买点、
分批建仓或抄底建议；这个模块的产品定位是**风险温度**，不是机会列表。

⚠️ ``/repair`` 比 ``/snapshot`` 贵得多：它要为每只跌停股拉一次日 K（逐只请求是行情源
风控主因），因此样本有上限（``limitdown_service._MAX_SAMPLES``）、结果缓存 6 小时。
前端应当**只在用户展开时**请求一次，不做轮询。

数据源是东财 ``push2ex`` 跌停板池（``getTopicDTPool``）—— 与 ``spot_service`` 的
``push2`` 全市场快照是不同域名/端点，push2 被风控时本模块不受影响，
因此这里**不接**快照那套冷却机制。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.services import limitdown_service

router = APIRouter(prefix="/api/limitdown", tags=["limitdown"])


@router.get("/snapshot")
async def snapshot(force: bool = False) -> dict:
    """当日跌停全景。

    ``force=true`` 穿透 60 秒内存缓存。跌停池是单次请求，代价远低于全市场快照，
    但盘中也没必要高频穿透，前端默认走缓存即可。
    """
    try:
        return await limitdown_service.get_snapshot(force=force)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/repair")
async def repair(
    days: int = Query(limitdown_service.MAX_REPAIR_DAYS, ge=2, le=30),
    force: bool = False,
) -> dict:
    """跌停次日修复收益回溯。

    默认取满接口回溯窗口（约 15 个交易日）。传更大的 ``days`` 不会扩大样本 ——
    更早的日期接口返回空池，会被识别为「无数据」并排除，可在返回体的
    ``empty_dates`` / ``data_window`` 里自查。``truncated=true`` 表示候选超过样本上限、
    只统计了最近的 N 个（以控请求量与函数超时）。
    """
    try:
        return await limitdown_service.repair_backtest(days=days, force=force)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
