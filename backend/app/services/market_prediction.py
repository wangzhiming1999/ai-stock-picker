"""明日大盘推衍：基于上证指数技术信号 + LLM 生成次日走势预判。"""
from __future__ import annotations

import akshare as ak
from openai import AsyncOpenAI

from app.config import get_settings
from app.services import signal_service

MARKET_INDEX = "sh000001"
MARKET_NAME = "上证指数"

PREDICTION_SYSTEM_PROMPT = """你是一位擅长 A 股大盘研判的资深策略分析师。基于用户提供的上证指数技术数据，预测明日大盘走势。

【输出要求】
只输出一个合法 JSON 对象，不要任何其他文字。结构如下：

{
  "direction": "上涨/震荡/下跌",
  "direction_score": 0到10的小数(>5偏多,<5偏空,=5中性),
  "expected_range": {"low": 预计最低点位, "high": 预计最高点位},
  "probability": "各方向概率，如：上涨40%/震荡35%/下跌25%",
  "key_levels": {"support1": "第一支撑", "support2": "第二支撑", "resistance1": "第一压力", "resistance2": "第二压力"},
  "summary": "120字以内的明日走势研判，先结论后逻辑",
  "drivers": ["2-4条影响明日走势的关键因素"],
  "trading_advice": "给散户的操作建议，含仓位、关注板块、风险提示"
}

【分析维度】
- 技术面：均线多头/空头、MACD 状态、RSI 超买超卖、布林带位置、量价配合
- 位置：指数处于近期区间的高位还是低位
- 情绪：结合当日涨跌和量能判断市场情绪
- 注意：仅基于提供的数据研判，数据不足时如实说明
- 预测仅供研究参考，不构成投资建议"""


def get_index_history(days: int = 180) -> list[dict]:
    """获取上证指数历史K线。"""
    df = ak.stock_zh_index_daily(symbol=MARKET_INDEX)
    df = df.tail(days)
    return [
        {
            "date": str(row["date"])[:10],
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]),
        }
        for _, row in df.iterrows()
    ]


def build_market_context(hist: list[dict]) -> tuple[str, dict]:
    """组装指数上下文 + 技术信号。"""
    closes = [h["close"] for h in hist]
    volumes = [h["volume"] for h in hist]
    last = hist[-1]
    price = last["close"]

    sig = signal_service.compute_signals(closes, price)

    # 当日涨跌
    prev = hist[-2]["close"] if len(hist) > 1 else price
    day_change = (price / prev - 1) * 100
    # 量比（当日 vs 前5日均量）
    vol_ratio = last["volume"] / (sum(volumes[-6:-1]) / 5) if len(volumes) >= 6 else 1
    # 近5日/20日涨幅
    ret5 = (price / closes[-6] - 1) * 100 if len(closes) >= 6 else 0
    ret20 = (price / closes[-21] - 1) * 100 if len(closes) >= 21 else 0
    # 区间位置
    low60 = min(closes[-60:]) if len(closes) >= 60 else min(closes)
    high60 = max(closes[-60:]) if len(closes) >= 60 else max(closes)
    pos = (price - low60) / (high60 - low60) * 100 if high60 > low60 else 50

    ctx = (
        f"指数：{MARKET_NAME}，最新收盘 {price:.2f}\n"
        f"当日涨跌 {day_change:+.2f}%，量比 {vol_ratio:.2f}\n"
        f"近5日 {ret5:+.2f}%，近20日 {ret20:+.2f}%，60日区间位置 {pos:.0f}%\n"
    )
    if sig:
        ctx += (
            f"技术信号：支撑 {sig['support']}，压力 {sig['resistance']}，"
            f"MA5 {sig['ma5']}，MA20 {sig['ma20']}，MA60 {sig['ma60']}，"
            f"RSI 由 MACD 等综合评估，布林上轨 {sig['bb_upper']}，下轨 {sig['bb_lower']}，"
            f"信号强度 {sig['strength']}\n"
        )
    ctx += f"近5日收盘：{', '.join(f'{c:.0f}' for c in closes[-5:])}"

    summary = {
        "price": price,
        "day_change": round(day_change, 2),
        "vol_ratio": round(vol_ratio, 2),
        "ret5": round(ret5, 2),
        "ret20": round(ret20, 2),
        "position_60d": round(pos, 1),
        "signal": sig,
    }
    return ctx, summary


async def predict_tomorrow() -> dict:
    """生成明日大盘走势预测。"""
    settings = get_settings()
    hist = await asyncio_hist()
    ctx, summary = build_market_context(hist)

    if not settings.deepseek_api_key:
        # 未配置 LLM：返回基于规则的基础预判
        return _rule_based_prediction(summary)

    client = AsyncOpenAI(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
    )
    stream = await client.chat.completions.create(
        model=settings.deepseek_model,
        messages=[
            {"role": "system", "content": PREDICTION_SYSTEM_PROMPT},
            {"role": "user", "content": ctx},
        ],
        stream=True,
        temperature=0.3,
    )
    parts: list[str] = []
    async for chunk in stream:
        if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
            parts.append(chunk.choices[0].delta.content)
    text = "".join(parts)

    import json
    import re

    prediction = {}
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            prediction = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            cleaned = text[start : end + 1].replace("```json", "").replace("```", "").strip()
            try:
                prediction = json.loads(cleaned)
            except json.JSONDecodeError:
                prediction = {}

    # LLM 输出缺失或损坏时回退规则预判
    if not prediction or "direction" not in prediction:
        rule = _rule_based_prediction(summary)
        rule["summary"]["summary"] = (
            "LLM 预测输出异常，已回退规则预判。"
            + rule["summary"].get("summary", "")
        )
        return rule

    return {
        "index": MARKET_NAME,
        "date": hist[-1]["date"],
        "summary": prediction,
        "technical": summary,
        "source": "llm",
    }


async def asyncio_hist() -> list[dict]:
    import asyncio

    return await asyncio.to_thread(get_index_history, 180)


def _rule_based_prediction(summary: dict) -> dict:
    """无 LLM 时的规则预判。"""
    sig = summary.get("signal") or {}
    strength = sig.get("strength", 5)
    price = summary["price"]
    ret5 = summary["ret5"]

    if strength >= 6 and ret5 > 0:
        direction, score = "上涨", 6.5
    elif strength >= 6:
        direction, score = "震荡偏强", 5.8
    elif strength >= 4:
        direction, score = "震荡", 5.0
    else:
        direction, score = "偏弱", 4.0

    return {
        "index": MARKET_NAME,
        "date": "",
        "summary": {
            "direction": direction,
            "direction_score": score,
            "expected_range": {
                "low": round(sig.get("support", price * 0.99), 0),
                "high": round(sig.get("resistance", price * 1.01), 0),
            },
            "probability": "请配置 LLM API Key 获取概率研判",
            "key_levels": {
                "support1": sig.get("support"),
                "resistance1": sig.get("resistance"),
            },
            "summary": f"基于技术信号强度 {strength} 与近期走势 {ret5:+.1f}% 的规则预判。配置 LLM 后可获得更详细研判。",
            "drivers": ["规则模式未分析驱动因素"],
            "trading_advice": "规则模式：建议控制仓位，等待 LLM 深度研判",
        },
        "technical": summary,
        "source": "rule",
    }
