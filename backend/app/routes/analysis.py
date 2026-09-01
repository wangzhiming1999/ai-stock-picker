"""选股分析接口：SSE 流式推送分析进度。"""
import asyncio
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app import store
from app.models import AnalysisRequest
from app.services import data_service
from app.services.llm_service import mock_analyze, parse_analysis, should_use_mock, stream_analyze

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


def _sse(event_type: str, message: str = "", payload: dict | None = None) -> str:
    data = json.dumps({"type": event_type, "message": message, "payload": payload}, ensure_ascii=False)
    return f"data: {data}\n\n"


@router.post("/stocks")
async def analyze_stocks(req: AnalysisRequest):
    """对一批股票逐个进行 AI 分析，SSE 流式返回进度和结果。"""

    async def event_generator():
        codes = [c.strip() for c in req.codes if c.strip()]
        if not codes:
            yield _sse("error", "请输入股票代码")
            return

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
        for q in quotes:
            yield _sse("stock_start", f"正在分析 {q.name}（{q.code}）...", {"code": q.code, "name": q.name})

            # 2. 组装上下文（K线 + 新闻）
            history = await asyncio.to_thread(data_service.get_history, q.code)
            news = await asyncio.to_thread(data_service.get_news, q.code, q.name)
            context = data_service.build_stock_context(q, history, news)

            # 3a. 本地规则评分模式
            if use_mock:
                analysis = await asyncio.to_thread(mock_analyze, q, history, news)
                analysis.code = q.code
                analysis.name = q.name
                results.append(analysis)
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
            results.append(analysis)
            yield _sse(
                "stock_done",
                f"{q.name} 评分 {analysis.overall_score:.1f} 分",
                {"code": q.code, "result": analysis.model_dump()},
            )

        # 5. 保存历史记录
        if results:
            try:
                batch_id = await asyncio.to_thread(
                    store.save_batch, codes, "mock" if use_mock else "llm", [r.model_dump() for r in results]
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
