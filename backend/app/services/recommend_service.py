"""每日收盘推荐：策略扫描候选 + LLM 精选 10 只并给出推荐理由。"""
from __future__ import annotations

import datetime as dt
import json

from openai import AsyncOpenAI

from app.config import get_settings
from app.routes import market as market_routes

# 每日推荐缓存：key=日期，value=(生成时间, data)。一天只跑一次。
_recommendation_cache: dict[str, tuple[str, dict]] = {}

RECOMMEND_SYSTEM_PROMPT = """你是一位资深的 A 股投资顾问，擅长从候选股票中挑选次日最具关注价值的标的。

【任务】
从用户提供的候选股票（含行情与技术信号）中，挑选 10 只最值得明日关注的股票，并为每只给出具体推荐理由。

【输出要求】
只输出一个合法的 JSON 数组，不要任何其他文字。格式如下：

[
  {
    "code": "600519",
    "name": "贵州茅台",
    "reason": "80字以内的推荐理由，结合提供的行情/技术数据说明为什么值得关注",
    "confidence": 0到10的置信分
  },
  ...
]

【挑选原则】
- 优先技术形态健康、量能配合、估值合理的标的
- 兼顾不同风格（动量/趋势/低估值/放量），不要全部集中一个方向
- 排除有明显风险信号（如已大幅上涨追高风险、停牌、ST）的标的
- 理由要具体，引用候选数据中的价格/涨跌幅/信号，不要空话
- 这是每日收盘后的次日关注推荐，强调"明日可跟踪观察"而非"盲目买入"
- 仅供研究参考，不构成投资建议"""


def clear_recommendation_cache() -> None:
    """清除缓存（用于测试或强制刷新场景）。"""
    _recommendation_cache.clear()


async def generate_daily_recommendations(force_refresh: bool = False) -> dict:
    """生成每日推荐：跑四个策略 → 合并候选 → LLM 精选 10 只。

    每天只跑一次，结果缓存到当日；force_refresh=True 时强制重跑。
    """
    today = dt.date.today().isoformat()
    if not force_refresh and today in _recommendation_cache:
        return _recommendation_cache[today][1]

    settings = get_settings()
    candidates: dict[str, dict] = {}

    # 1. 跑四个策略收集候选
    for strategy in ("momentum", "trend", "value", "volume"):
        try:
            results = await _scan_strategy(strategy)
            for item in results:
                code = item["code"]
                # 合并：保留更高策略分
                if code not in candidates or item["strategy_score"] > candidates[code]["strategy_score"]:
                    candidates[code] = item
        except Exception as e:
            print(f"[recommend] strategy {strategy} failed: {e}")

    # 2. 按策略分排序取 top 15
    ranked = sorted(candidates.values(), key=lambda x: x["strategy_score"], reverse=True)[:15]
    if not ranked:
        result = {"date": today, "source": "empty", "recommendations": [], "candidates": 0, "message": "没有找到合适的候选股票（可能是非交易日或盘前）"}
        _recommendation_cache[today] = (dt.datetime.now().isoformat(), result)
        return result

    # 3. 构造候选上下文
    ctx_lines = ["以下是候选股票（含实时行情与技术信号），请从中挑选明日最值得关注的 10 只：\n"]
    for i, c in enumerate(ranked, 1):
        sig = c.get("indicators") or {}
        sig_txt = "，".join(f"{k}={v}" for k, v in sig.items() if v is not None) if sig else "无详细指标"
        ctx_lines.append(
            f"{i}. {c['name']}({c['code']}) 现价{c['price']} 涨跌{c['change_pct']}% "
            f"PE={c.get('pe')} PB={c.get('pb')} 换手={c.get('turnover')}% "
            f"策略分={c['strategy_score']} 信号={'/'.join(c.get('tags', []))} 指标[{sig_txt}]"
        )
    ctx = "\n".join(ctx_lines)

    # 4. LLM 精选
    recs: list[dict] = []
    source = "rule"
    if settings.deepseek_api_key:
        try:
            client = AsyncOpenAI(api_key=settings.deepseek_api_key, base_url=settings.deepseek_base_url)
            stream = await client.chat.completions.create(
                model=settings.deepseek_model,
                messages=[
                    {"role": "system", "content": RECOMMEND_SYSTEM_PROMPT},
                    {"role": "user", "content": ctx},
                ],
                temperature=0.3,
            )
            parts: list[str] = []
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                    parts.append(chunk.choices[0].delta.content)
            text = "".join(parts)
            start, end = text.find("["), text.rfind("]")
            if start != -1 and end > start:
                parsed = json.loads(text[start : end + 1])
                if isinstance(parsed, list):
                    # 用候选中的真实行情数据补全
                    info_map = {c["code"]: c for c in ranked}
                    recs = []
                    for p in parsed[:10]:
                        code = str(p.get("code", "")).strip()
                        info = info_map.get(code)
                        if info:
                            recs.append(
                                {
                                    "code": code,
                                    "name": info["name"],
                                    "price": info["price"],
                                    "change_pct": info["change_pct"],
                                    "reason": str(p.get("reason", "")),
                                    "confidence": float(p.get("confidence", 5)),
                                    "tags": info.get("tags", []),
                                }
                            )
                    source = "llm"
        except Exception as e:
            print(f"[recommend] LLM 失败，回退规则: {e}")

    # 5. 回退：规则模式取 top 10
    if not recs:
        for c in ranked[:10]:
            recs.append(
                {
                    "code": c["code"],
                    "name": c["name"],
                    "price": c["price"],
                    "change_pct": c["change_pct"],
                    "reason": f"策略分 {c['strategy_score']}，信号：{'/'.join(c.get('tags', []))}。配置 LLM 后可获得更详细的推荐理由。",
                    "confidence": c["strategy_score"],
                    "tags": c.get("tags", []),
                }
            )

    result = {
        "date": today,
        "source": source,
        "recommendations": recs,
        "candidates": len(ranked),
    }
    _recommendation_cache[today] = (dt.datetime.now().isoformat(), result)
    return result


async def _scan_strategy(strategy: str) -> list[dict]:
    """对指定策略跑一次扫描（复用市场路由的逻辑）。"""
    from app.services import data_service

    spot = await market_routes._get_spot()
    candidates = []
    for row in spot:
        name = row.get("name", "")
        price = row.get("price", 0)
        if any(x in name for x in ("ST", "退", "N", "C")):
            continue
        if price <= 1 or price > 500:
            continue
        if row["amount"] / 1e8 < 3:
            continue
        code = row["code"].replace("sh", "").replace("sz", "").replace("bj", "")
        candidates.append(code)
    codes = candidates[:40]
    return await market_routes._apply_strategy(codes, strategy)
