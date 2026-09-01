"""LLM 分析服务：调用 DeepSeek（OpenAI 兼容）对流式输出个股分析；未配置 Key 时使用本地规则评分。"""
from __future__ import annotations

import json
from typing import AsyncIterator

from openai import AsyncOpenAI

from app.config import get_settings
from app.models import NewsItem, StockAnalysis, StockHistory, ScoreDimension, StockQuote

ANALYSIS_SYSTEM_PROMPT = """你是一位专业的 A 股量化分析师，擅长结合基本面、技术面、资金面和消息面综合分析股票投资价值。

请对用户提供的股票数据进行分析，严格按照以下 JSON 结构输出（不要输出任何其他文字）：

{
  "overall_score": 0到10的整数或小数,
  "summary": "100字以内的综合点评",
  "dimensions": [
    {"name": "基本面", "score": 0-10, "comment": "点评"},
    {"name": "技术面", "score": 0-10, "comment": "点评"},
    {"name": "资金面", "score": 0-10, "comment": "点评"},
    {"name": "消息面", "score": 0-10, "comment": "点评"}
  ],
  "risks": ["风险点1", "风险点2"],
  "suggestions": ["操作建议1", "操作建议2"]
}

评分标准：
- 基本面：关注市盈率/市净率的合理程度、市值规模
- 技术面：关注均线排列、趋势、区间位置
- 资金面：关注换手率、成交量活跃度
- 消息面：关注新闻中是否有正面/负面催化

注意：评分要客观审慎，默认给中性分，只有数据确实支持才给高分或低分。最后输出必须是合法的 JSON 对象。"""


async def stream_analyze(quote: StockQuote, context: str) -> AsyncIterator[str]:
    """流式调用 LLM，yield 原始文本增量。"""
    settings = get_settings()
    if not settings.deepseek_api_key:
        raise ValueError("未配置 DEEPSEEK_API_KEY，请在 backend/.env 中配置")

    client = AsyncOpenAI(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
    )
    stream = await client.chat.completions.create(
        model=settings.deepseek_model,
        messages=[
            {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
            {"role": "user", "content": context},
        ],
        stream=True,
        temperature=0.3,
    )
    async for chunk in stream:
        if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content


def mock_analyze(quote: StockQuote, history: StockHistory | None, news: list[NewsItem]) -> StockAnalysis:
    """本地规则评分（未配置 API Key 时的兜底，便于无 Key 体验完整流程）。

    规则要点：
    - 技术面：均线多头排列加分，价格站上 MA5 加分，区间跌幅过深扣分
    - 基本面：PE 在 10~40 视为合理，过高扣分
    - 资金面：换手率 1%~10% 视为活跃健康
    - 消息面：新闻数量作为关注度参考
    """
    dims: list[ScoreDimension] = []
    risks: list[str] = []
    suggestions: list[str] = []

    # ---- 基本面 ----
    pe = quote.pe
    pb = quote.pb
    base_score = 5.0
    base_comments: list[str] = []
    if pe is not None:
        if 0 < pe <= 10:
            base_score += 2.0
            base_comments.append(f"市盈率 {pe:.1f} 偏低，估值有吸引力")
        elif 10 < pe <= 25:
            base_score += 1.0
            base_comments.append(f"市盈率 {pe:.1f} 处于合理区间")
        elif 25 < pe <= 40:
            base_comments.append(f"市盈率 {pe:.1f} 偏高，需业绩消化估值")
        elif pe > 40:
            base_score -= 1.5
            base_comments.append(f"市盈率 {pe:.1f} 明显偏高，注意估值风险")
    if pb is not None:
        if pb > 10:
            base_score -= 0.5
            base_comments.append(f"市净率 {pb:.1f} 较高")
    if quote.market_cap and quote.market_cap >= 1e12:
        base_comments.append("大盘蓝筹，抗风险能力较强")
    dims.append(ScoreDimension(name="基本面", score=max(0, min(10, base_score)), comment="；".join(base_comments) or "数据有限"))

    # ---- 技术面 ----
    tech_score = 5.0
    tech_comments: list[str] = []
    if history and history.closes:
        closes = history.closes
        price = quote.price
        ma5 = sum(closes[-5:]) / 5
        ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else ma5
        if price >= ma5:
            tech_score += 1.5
            tech_comments.append(f"现价站上 MA5({ma5:.2f})")
        else:
            tech_score -= 1.0
            tech_comments.append(f"现价跌破 MA5({ma5:.2f})")
        if ma5 > ma20:
            tech_score += 1.5
            tech_comments.append("短期均线多头排列")
        else:
            tech_score -= 1.0
            tech_comments.append("短期均线偏弱")
        if len(closes) >= 60:
            ma60 = sum(closes[-60:]) / 60
            if price >= ma60:
                tech_comments.append("中期趋势向上")
                tech_score += 0.5
            else:
                tech_comments.append("中期趋势承压")
                tech_score -= 0.5
        recent_ret = (closes[-1] / closes[-10] - 1) * 100 if len(closes) >= 10 and closes[-10] else 0
        if recent_ret < -10:
            tech_score -= 1.0
            tech_comments.append(f"近10日跌幅 {recent_ret:.1f}%，短期弱势")
    dims.append(ScoreDimension(name="技术面", score=max(0, min(10, tech_score)), comment="；".join(tech_comments) or "数据有限"))

    # ---- 资金面 ----
    fund_score = 5.0
    fund_comments: list[str] = []
    if quote.turnover is not None:
        t = quote.turnover
        if t <= 0.5:
            fund_comments.append(f"换手率 {t:.2f}% 偏低，交投清淡")
        elif t <= 3:
            fund_score += 1.0
            fund_comments.append(f"换手率 {t:.2f}% 适中，交投健康")
        elif t <= 10:
            fund_score += 0.5
            fund_comments.append(f"换手率 {t:.2f}% 活跃，关注资金动向")
        else:
            fund_score -= 1.5
            fund_comments.append(f"换手率 {t:.2f}% 过高，警惕炒作风险")
    dims.append(ScoreDimension(name="资金面", score=max(0, min(10, fund_score)), comment="；".join(fund_comments) or "数据有限"))

    # ---- 消息面 ----
    news_score = 5.0
    news_comments: list[str] = []
    if news:
        news_comments.append(f"近期有 {len(news)} 条相关新闻，关注度较高")
        news_score += min(1.0, len(news) * 0.2)
    else:
        news_comments.append("未获取到针对性新闻")
    dims.append(ScoreDimension(name="消息面", score=max(0, min(10, news_score)), comment="；".join(news_comments)))

    overall = sum(d.score for d in dims) / len(dims)

    if quote.price <= 0:
        risks.append("最新价为 0，可能是停牌或数据异常")
    if pe and pe > 40:
        risks.append("估值偏高，存在业绩不及预期引发回调的风险")
    if history and history.closes and (history.closes[-1] / history.closes[0] - 1) * 100 < -15:
        risks.append("近期累计跌幅较大，短期趋势偏弱")

    if overall >= 7:
        suggestions.append("可考虑逢低分批关注")
    elif overall >= 5:
        suggestions.append("可观察等待更好的介入时机")
    else:
        suggestions.append("建议回避或等待企稳信号")
    suggestions.append("严格控制仓位，设置止损")

    return StockAnalysis(
        code=quote.code,
        name=quote.name,
        overall_score=round(overall, 1),
        summary=f"基于行情与技术面的规则评分模型给出综合评分 {overall:.1f} 分。"
        f"{dims[0].comment}；{dims[1].comment}。配置 DEEPSEEK_API_KEY 后可获得 LLM 深度分析。",
        dimensions=dims,
        risks=risks,
        suggestions=suggestions,
    )


def should_use_mock() -> bool:
    """判断当前是否应使用本地规则评分。"""
    settings = get_settings()
    if settings.llm_mode == "mock":
        return True
    if settings.llm_mode == "real":
        return not settings.deepseek_api_key  # real 但没 key 时只能兜底 mock
    return not settings.deepseek_api_key  # auto


def parse_analysis(text: str) -> StockAnalysis:
    """从 LLM 输出文本中解析出结构化结果。"""
    # 提取最外层的 JSON 花括号内容
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("LLM 输出中未找到有效 JSON")

    raw = text[start : end + 1]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # 尝试去掉可能的 markdown 代码块
        cleaned = raw.replace("```json", "").replace("```", "").strip()
        data = json.loads(cleaned)

    dimensions = [
        {"name": d.get("name", ""), "score": float(d.get("score", 0)), "comment": d.get("comment", "")}
        for d in data.get("dimensions", [])
    ]
    return StockAnalysis(
        code="",
        name="",
        overall_score=float(data.get("overall_score", 0)),
        summary=data.get("summary", ""),
        dimensions=dimensions,
        risks=[str(r) for r in data.get("risks", [])],
        suggestions=[str(s) for s in data.get("suggestions", [])],
    )
