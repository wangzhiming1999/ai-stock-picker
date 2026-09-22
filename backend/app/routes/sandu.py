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
from app.services.spot_service import fetch_fund_flow_rows

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


@router.get("/auto-candidates")
async def auto_candidates(count: int = 20) -> dict:
    """自动挑一批三度扫描候选：当日主力净流入榜（吸筹侧）前列。

    数据源是东财资金流 clist **批量单请求**（max_pages=1，一页 200 行），
    与全市场快照同纪律，不做逐只请求 —— 候选生成阶段零逐股 I/O；
    逐只日 K 仍由 /scan 按用户确认后的候选拉取。

    过滤：剔除 ST/退市、北交所（8/4/92 开头）；只留主力净流入 > 0 的吸筹侧。
    失败时抛 RuntimeError → 500，由前端按行情源故障提示（不静默给空名单）。
    """
    count = max(5, min(count, 30))
    rows = await asyncio.to_thread(fetch_fund_flow_rows, "f62", False, 1)

    candidates: list[dict] = []
    for row in rows:
        code = str(row.get("code") or "")
        name = str(row.get("name") or "")
        main_net = row.get("main_net")
        if "ST" in name.upper() or "退" in name:
            continue
        # 只留沪深主板 / 创业板 / 科创板，剔除北交所
        if not (len(code) == 6 and (code[:2] in {"60", "00"} or code[:3] in {"300", "301", "302", "688"})):
            continue
        if main_net is None or main_net <= 0:
            continue
        candidates.append(
            {
                "code": code,
                "name": name,
                "main_net": main_net,
                "change_pct": row.get("change_pct"),
            }
        )
        if len(candidates) >= count:
            break

    return {"source": "fund_flow_main_net", "count": len(candidates), "candidates": candidates}


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
