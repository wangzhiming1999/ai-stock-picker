"""选股分析接口：SSE 流式推送分析进度。"""
import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app import store
from app.models import AnalysisRequest, StockHistory
from app.services import data_service, debate_service, pattern_service, signal_service, supabase_store, trend_template_service
from app.services.llm_service import mock_analyze, parse_analysis, should_use_mock, stream_analyze

router = APIRouter(prefix="/api/analysis", tags=["analysis"])

# 深度分析要跑全部形态技巧，其中「多周期共振」需要月线 MACD（约 35 个月 ≈ 735 个交易日），
# 故日线取 900 根；而技术信号 / 趋势模板 / LLM 上下文仍只喂最近 260 根切片，保持原有输出不变。
_ANALYSIS_DAYS = 900
_CONTEXT_DAYS = 260


def _tail_history(hist: StockHistory | None, days: int) -> StockHistory | None:
    """截取最近 days 根 K 线，OHLCV 各序列同步截尾（长度不足则原样返回）。"""
    if not hist or not hist.closes:
        return None
    if len(hist.closes) <= days:
        return hist

    def _tail(values: list | None) -> list | None:
        return values[-days:] if values else None

    return StockHistory(
        dates=hist.dates[-days:],
        closes=hist.closes[-days:],
        volumes=_tail(hist.volumes),
        opens=_tail(hist.opens),
        highs=_tail(hist.highs),
        lows=_tail(hist.lows),
    )


def _tactic_ctx(quote, history: StockHistory | None, intraday=None, extra: dict | None = None) -> dict:
    """组装形态判定上下文（与 pattern_service 的 ctx 约定一致）。

    extra 为按周期取到的周线/月线（`pattern_service.load_tactic_periods`），
    多周期共振要靠它才能用真实月线判定；其余技巧忽略该字段。
    """
    ctx = {
        "daily": history,
        "intraday": intraday,
        "price": quote.price,
        "turnover": quote.turnover,
    }
    if extra:
        ctx.update(extra)
    return ctx


def _cache_needs_tactics(cached: dict) -> bool:
    """缓存里的形态结果是否需要重算。

    两种情况：完全没有形态字段；或有但缺 `evidence`（证据闸门上线前的旧行）。
    旧行必须重算而不是沿用 —— 前端对缺字段的结果只能兜底成「未验证」，
    那会让用户看到错误的等级（真实等级可能是「初步」）。
    """
    tactics = cached.get("tactics")
    if not isinstance(tactics, list):
        return True
    return any(isinstance(t, dict) and "evidence" not in t for t in tactics)


async def _assemble_context(q):
    """拉行情 / 新闻 / K 线并组装分析上下文。

    深度分析主链路与「缓存命中但要求补跑辩论」共用 —— 两处需要的上下文完全一致，
    不抽出来就会复制出第二份口径，将来改 context 拼法必然漂掉一处。
    """
    long_history = await asyncio.to_thread(data_service.get_history, q.code, _ANALYSIS_DAYS)
    history = _tail_history(long_history, _CONTEXT_DAYS)
    news = await asyncio.to_thread(data_service.get_news, q.code, q.name)
    context = data_service.build_stock_context(q, history, news)

    signal = None
    strategy_assessment = None
    if history and history.closes:
        signal = signal_service.compute_signals(history.closes, q.price)
        strategy_assessment = trend_template_service.assess_trend_template(history.closes, q.price)
        if signal:
            context += (
                f"\n\n技术位（由系统计算）：支撑位 {signal['support']}，压力位 {signal['resistance']}，"
                f"建议买入区 {signal['buy_point']}，建议卖出区 {signal['sell_point']}，"
                f"止损位 {signal['stop_loss']}，风险收益比 {signal['rr_ratio']}，"
                f"信号强度 {signal['strength']}。请结合这些技术位给出更精确的买卖建议。"
            )
        context += (
            f"\n\n长期趋势质量检查：{strategy_assessment['passed']}/{strategy_assessment['total']} 项通过，"
            f"系统结论：{strategy_assessment['action']}。这是筛选条件，不是买入信号。"
        )

    # 形态命中：K 线量价条件的确定性核对结果（仅全部条件成立才算命中）
    extra_periods = await pattern_service.load_tactic_periods([q.code])
    tactics = pattern_service.matched_tactics(
        _tactic_ctx(q, long_history, extra=extra_periods.get(q.code))
    )
    if tactics:
        hits = "；".join(f"{t['name']}（{t['action']}）" for t in tactics)
        context += f"\n\n系统形态识别命中：{hits}。这是确定性条件核对结果，请结合它评估风险与操作节奏。"

    return {
        "long_history": long_history,
        "history": history,
        "news": news,
        "signal": signal,
        "strategy": strategy_assessment,
        "tactics": tactics,
        "context": context,
    }


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
                # 旧缓存缺少规则字段（趋势模板 / 形态命中 / 形态证据等级）时就地补齐，
                # 避免用户要等到次日才看到新结果 —— 尤其是证据等级：缺失会让前端把
                # 未验证形态按「买点」渲染（前端虽有兜底，但缓存里补上才是真正的修复）。
                needs_patch = _cache_needs_tactics(cached)
                if "strategy" not in cached or needs_patch:
                    cached_history = await asyncio.to_thread(data_service.get_history, q.code, _ANALYSIS_DAYS)
                    if cached_history and cached_history.closes:
                        if "strategy" not in cached:
                            context_history = _tail_history(cached_history, _CONTEXT_DAYS) or cached_history
                            cached["strategy"] = trend_template_service.assess_trend_template(
                                context_history.closes, q.price
                            )
                        if needs_patch:
                            cached_extra = await pattern_service.load_tactic_periods([q.code])
                            cached["tactics"] = pattern_service.matched_tactics(
                                _tactic_ctx(q, cached_history, extra=cached_extra.get(q.code))
                            )
                if req.debate and not cached.get("debate"):
                    # 用户显式开了辩论，但今日缓存是没开辩论时写的 —— 就地补跑并回写。
                    # 不补的话开关像「不生效」，要等次日缓存过期才能看到辩论。
                    prepared = await _assemble_context(q)
                    debate = await debate_service.run_debate(prepared["context"])
                    if debate:
                        cached["debate"] = debate.model_dump()
                        await _write_cache(q.code, cached, source="debate_patch")
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

            # 2. 组装上下文（K线 + 新闻 + 技术信号 + 形态）
            # 日线请求 900 根（行情源硬上限 640），下游一律传最近 260 根切片，
            # 保证技术信号 / 趋势模板 / LLM 上下文的输入与改动前完全一致。
            prepared = await _assemble_context(q)
            history = prepared["history"]
            news = prepared["news"]
            signal = prepared["signal"]
            strategy_assessment = prepared["strategy"]
            tactics = prepared["tactics"]
            context = prepared["context"]

            # 2.5 多空研究员辩论（仅在请求显式开启；无 Key / 失败一律降级为 None）
            # 只把「分歧」喂给主分析，不喂「倾向」—— 见 debate_service.summarize 的说明。
            debate = None
            if req.debate and not use_mock:
                yield _sse(
                    "debate_start",
                    f"{q.name} 多空研究员对辩中（额外 2 轮 LLM 调用）...",
                    {"code": q.code},
                )
                debate = await debate_service.run_debate(context)
                if debate:
                    context += f"\n\n{debate_service.summarize(debate)}"
                    yield _sse(
                        "debate_done",
                        f"{q.name} 多空分歧度 {debate.divergence:.0f}/100",
                        {"code": q.code},
                    )
                else:
                    yield _sse(
                        "debate_done",
                        f"{q.name} 辩论未产出（已降级，不影响主分析）",
                        {"code": q.code},
                    )

            # 3a. 本地规则评分模式
            if use_mock:
                analysis = await asyncio.to_thread(mock_analyze, q, history, news)
                analysis.code = q.code
                analysis.name = q.name
                if signal:
                    analysis.signal = signal_service.compute_signals(history.closes, q.price)
                analysis.strategy = strategy_assessment
                analysis.tactics = tactics
                analysis.debate = debate  # 规则评分模式下恒为 None（无 Key，辩论没有推理后端）
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
            analysis.strategy = strategy_assessment
            analysis.tactics = tactics
            analysis.debate = debate
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

        yield _sse(
            "done",
            "全部分析完成",
            {"results": [r if isinstance(r, dict) else r.model_dump() for r in results]},
        )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
