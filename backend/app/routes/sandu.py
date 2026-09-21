"""三度交易理论选股接口。

POST /api/sandu/scan
  入参：候选代码列表（≤30）+ 综合分门槛。
  行为：逐只按并发上限拉日线（腾讯，带缓存），做三度打分，按综合分降序返回。

⚠️ 风控：
  - 逐只历史 K 走 `concurrency.gather_limited(limit=8)`，信号量只包叶子 I/O，
    与全站其它批量拉取共用同一进程级配额，绝不裸 asyncio.gather。
  - 不 force、不扫全市场：候选由调用方显式给出（与 /api/analysis 同纪律），
    避免触发行情源 IP 级风控。
  - 行情源整体故障时不抛 500：单只缺失 → insufficient_data，整体返回部分结果。
"""

import asyncio
from typing import List

from fastapi import APIRouter

from app.models import SanduItem, SanduScanRequest, SanduScanResult
from app.services import data_service
from app.services.concurrency import gather_limited
from app.services.sandu_service import score_sandu

router = APIRouter(prefix="/api/sandu", tags=["sandu"])


def _empty_item(code: str, reason: str) -> SanduItem:
    return SanduItem(
        code=code,
        name="",
        thickness=0.0,
        strength=0.0,
        velocity=0.0,
        overall=0.0,
        status="insufficient_data",
        zone=None,
        action=reason,
        reasons=[reason],
    )


@router.post("/scan", response_model=SanduScanResult)
async def scan_sandu(req: SanduScanRequest) -> SanduScanResult:
    codes = [c.strip() for c in req.codes if c.strip()]

    # 一次性批量取名称 / 现价（腾讯批量接口，单请求），失败降级为空映射
    spot_map: dict[str, object] = {}
    try:
        quotes = await asyncio.to_thread(data_service.get_spot_quote, codes)
        for q in quotes:
            spot_map[q.code] = q
    except Exception:  # noqa: BLE001 — 行情源故障不阻断扫描，缺失项降级
        spot_map = {}

    # 逐只拉日线（叶子 I/O，受全局并发配额保护）
    async def _fetch_one(code: str):
        return await asyncio.to_thread(data_service.get_history, code, 120)

    raw = await gather_limited((_fetch_one(c) for c in codes), return_exceptions=True)

    items: List[SanduItem] = []
    missing = 0
    for code, hist in zip(codes, raw):
        if isinstance(hist, Exception) or hist is None:
            missing += 1
            items.append(_empty_item(code, "K 线取数失败或历史不足，无法判断三度"))
            continue

        result = score_sandu(hist)
        quote = spot_map.get(code)
        name = getattr(quote, "name", "") or ""
        price = getattr(quote, "price", None)
        change_pct = getattr(quote, "change_pct", None)

        items.append(
            SanduItem(
                code=code,
                name=name,
                price=price,
                change_pct=change_pct,
                thickness=result["thickness"],
                strength=result["strength"],
                velocity=result["velocity"],
                overall=result["overall"],
                status=result["status"],
                zone=result["zone"],
                action=result["action"],
                reasons=result["reasons"],
                dimensions=result["dimensions"],  # list[dict] 由 response_model 自动校验为 SanduDimension
            )
        )

    # 过滤门槛 + 综合分降序
    if req.min_overall > 0:
        items = [it for it in items if it.overall >= req.min_overall]
    items.sort(key=lambda it: it.overall, reverse=True)

    notice = None
    if missing:
        notice = f"{missing} 只取数失败（行情源故障或历史不足），已降级为 insufficient_data"

    return SanduScanResult(
        count=len(items),
        scanned=len(codes),
        items=items,
        notice=notice,
    )
