"""选股分析接口：SSE 流式推送分析进度。"""
import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app import store
from app.models import AnalysisRequest
from app.services import data_service, signal_service, supabase_store
from app.services.llm_service import mock_analyze, parse_analysis, should_use_mock, stream_analyze

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


def _sse(event_type: str, message: str = "", payload: dict | None = None) -> str:
    data = json.dumps({"type": event_type, "message": message, "payload": payload}, ensure_ascii=False)
    return f"data: {data}\n\n"


@router.post("/stocks")
async def analyze_stocks(req: AnalysisRequest, request: Request):
    """对一批股票逐个进行 AI 分析，SSE 流式返回进度和结果。"""

    async def event_generator():
        codes = [c.strip() for c in req.codes if c.strip()]
        if not codes:
            yield _sse("error", "请输入股票代码")
            return

        # 解析用户（配置了 Supabase 且带 token 时关联历史到用户）
        user_id = None
        if supabase_store.is_configured():
            auth = request.headers.get("authorization", "")
            if auth.lower().startswith("bearer "):
                token = auth.split(" ", 1)[1].strip()
                user = await supabase_store.get_user_by_token(token)
                user_id = user.id if user else None

        yield _sse("status", f"开始获取 {len(codes)} 只股票的行情数据...")

        use_mock = should_use_mock()
        if use_mock:
            yield _sse("status", "未配置 LLM API Key，使用本地规则评分模式（配置 DEEPSEEK_API_KEY 后可获得 AI 深度分析）")

        # 1. 拉取全部行情
        quotes = await asyncio.to_thread(data_service.get_spot_quote, codes)
        quote_map = {q.code: q for q in quotes}
        if not quotes:
            yield _sse("error", "未获取到任何行情数据，请检查股票代码")
            return

        yield _sse("status", f"获取到 {len(quotes)} 只股票行情，开始逐一分析...")

        results = []
        # 当前交易日（按交易日缓存：每天每只股票只跑一次 LLM）
        from app.services import trade_calendar_service

        data_day = await trade_calendar_service.last_trading_day()
        cache_date = data_day.isoformat()
        cached_map: dict[str, dict] = {}
        cache_sb = None
        if supabase_store.is_configured():
            cache_sb = await supabase_store.get_service_client()
            if not req.force:
                try:
                    code_list = [q.code for q in quotes]
                    res = (
                        await cache_sb.table("stock_analysis_cache")
                        .select("code, result")
                        .eq("data_date", cache_date)
                        .in_("code", code_list)
                        .execute()
                    )
                    for row in res.data or []:
                        cached_map[row["code"]] = row["result"]
                except Exception as e:
                    print(f"[analysis] 读缓存失败: {e}")

        async def _write_cache(code: str, payload: dict, source: str):
            """写入今日缓存（upsert，失败不影响主流程）。"""
            if cache_sb is None:
                return
            try:
                await cache_sb.table("stock_analysis_cache").upsert(
                    {
                        "code": code,
                        "data_date": cache_date,
                        "result": payload,
                        "source": source,
                    }
                ).execute()
            except Exception as e:
                print(f"[analysis] 写缓存失败 {code}: {e}")

        for q in quotes:
            # 1. 缓存命中：直接返回（force=False 时）
            if not req.force and q.code in cached_map:
                cached = cached_map[q.code]
                yield _sse(
                    "stock_start",
                    f"{q.name}（{q.code}）命中今日缓存...",
                    {"code": q.code, "name": q.name},
                )
                cached["code"] = q.code
                cached["name"] = q.name
                score = cached.get("overall_score", 0)
                results.append(cached)
                yield _sse(
                    "stock_done",
                    f"{q.name} 评分 {score:.1f} 分（缓存）",
                    {"code": q.code, "result": cached, "cached": True},
                )
                continue

            yield _sse("stock_start", f"正在分析 {q.name}（{q.code}）...", {"code": q.code, "name": q.name})

            # 2. 组装上下文（K线 + 新闻 + 技术信号）
            history = await asyncio.to_thread(data_service.get_history, q.code)
            news = await asyncio.to_thread(data_service.get_news, q.code, q.name)
            context = data_service.build_stock_context(q, history, news)

            signal = None
            if history and history.closes:
                signal = signal_service.compute_signals(history.closes, q.price)
                if signal:
                    context += (
                        f"\n\n技术位（由系统计算）：支撑位 {signal['support']}，压力位 {signal['resistance']}，"
                        f"建议买入区 {signal['buy_point']}，建议卖出区 {signal['sell_point']}，"
                        f"止损位 {signal['stop_loss']}，风险收益比 {signal['rr_ratio']}，"
                        f"信号强度 {signal['strength']}。请结合这些技术位给出更精确的买卖建议。"
                    )

            # 3a. 本地规则评分模式
            if use_mock:
                analysis = await asyncio.to_thread(mock_analyze, q, history, news)
                analysis.code = q.code
                analysis.name = q.name
                if signal:
                    analysis.signal = signal_service.compute_signals(history.closes, q.price)
                results.append(analysis)
                await _write_cache(q.code, analysis.model_dump(), source="rule")
                yield _sse(
                    "stock_done",
                    f"{q.name} 评分 {analysis.overall_score:.1f} 分",
                    {"code": q.code, "result": analysis.model_dump()},
                )
                continue

            # 3b. 流式调用 LLM
            buffer: list[str] = []
            try:
                async for delta in stream_analyze(q, context):
                    buffer.append(delta)
                    yield _sse("delta", delta, {"code": q.code})
            except Exception as e:
                yield _sse("stock_error", f"{q.name} 分析失败：{e}", {"code": q.code})
                continue

            # 4. 解析结果
            raw_text = "".join(buffer)
            try:
                analysis = parse_analysis(raw_text)
            except Exception:
                yield _sse("stock_error", f"{q.name} 结果解析失败", {"code": q.code})
                continue

            analysis.code = q.code
            analysis.name = q.name
            if signal:
                analysis.signal = signal_service.compute_signals(history.closes, q.price)
            results.append(analysis)
            await _write_cache(q.code, analysis.model_dump(), source="llm")
            yield _sse(
                "stock_done",
                f"{q.name} 评分 {analysis.overall_score:.1f} 分",
                {"code": q.code, "result": analysis.model_dump()},
            )

        # 5. 保存历史记录
        if results:
            try:
                result_dicts = [r if isinstance(r, dict) else r.model_dump() for r in results]
                if supabase_store.is_configured():
                    batch_id = await supabase_store.save_batch(
                        user_id, codes, "mock" if use_mock else "llm", result_dicts
                    )
                else:
                    batch_id = await asyncio.to_thread(
                        store.save_batch, codes, "mock" if use_mock else "llm", result_dicts
                    )
                yield _sse("batch_saved", "分析结果已保存到历史记录", {"batch_id": batch_id})
            except Exception as e:
                yield _sse("status", f"历史保存失败（不影响结果）：{e}")

        yield _sse("done", "全部分析完成", {"results": [r.model_dump() for r in results]})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
