"""明日大盘推衍：基于上证指数技术信号 + LLM 生成次日走势预判，并记录/结算预测准确率。"""
from __future__ import annotations

import asyncio
import datetime as dt

import akshare as ak
from openai import AsyncOpenAI

from app.config import get_settings
from app.services import signal_service, supabase_store, trade_calendar_service

MARKET_INDEX = "sh000001"
MARKET_NAME = "上证指数"

# 每日大盘推衍缓存：key=日期，value=(生成时间, data)。一天只跑一次。
_prediction_cache: dict[str, tuple[str, dict]] = {}

PREDICTION_SYSTEM_PROMPT = """你是一位擅长 A 股大盘研判的资深策略分析师，风格类似同花顺/指南针的收盘复盘研报。基于用户提供的上证指数【最新交易日收盘后】技术数据，研判【下一个交易日】的走势。

【核心概念：交易日（T 日）】
- A 股只在交易日开盘（周一至周五，法定节假日休市）
- 你收到的数据是最近一个已收盘交易日（记为 T）的收盘数据
- 你要预测的是 T 之后的下一个交易日（T+1）
- 如果 T 是周五，T+1 就是下周一，中间周末不预测

【输出要求】
只输出一个合法 JSON 对象，不要任何其他文字。结构如下：

{
  "direction": "上涨/震荡/下跌",
  "direction_score": 0到10的小数(>5偏多,<5偏空,=5中性),
  "expected_range": {"low": 预计最低点位, "high": 预计最高点位},
  "probability": "各方向概率，如：上涨40%/震荡35%/下跌25%",
  "key_levels": {"support1": "第一支撑", "support2": "第二支撑", "resistance1": "第一压力", "resistance2": "第二压力"},
  "summary": "120字以内的下一个交易日走势研判，先结论后逻辑，句式像专业复盘报告",
  "drivers": ["2-4条影响下一个交易日走势的关键因素"],
  "trading_advice": "给散户的操作建议，含建议仓位、关注板块、风险提示"
}

【分析维度】
- 技术面：均线多头/空头排列、MACD 金叉死叉状态、RSI 是否超买超卖、布林带位置、量价是否配合
- 位置与空间：指数处于近期 60 日区间的高位还是低位，距离支撑/压力位的空间
- 情绪与节奏：结合当日涨跌幅、量比、5日/20日动量判断市场情绪强弱
- 多空博弈：结合关键点位给出多空分水岭
【写作风格】
- summary 要像专业股评：先给结论方向，再用数据支撑逻辑，避免空话套话
- drivers 要具体可验证（技术信号/量能/位置），不要泛泛而谈
【注意】
- 仅基于提供的数据研判，数据不足时如实说明，绝不编造
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


def build_market_context(hist: list[dict], data_day: dt.date | None = None, next_day: dt.date | None = None) -> tuple[str, dict]:
    """组装指数上下文 + 技术信号 + 交易日信息。"""
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

    # 交易日（T / T+1）语义
    data_day_s = data_day.isoformat() if data_day else (hist[-1]["date"] if hist else "-")
    next_day_s = next_day.isoformat() if next_day else "下一交易日"

    ctx = (
        f"【交易日基准】数据基于 {data_day_s}（交易日 T）收盘；请预测 {next_day_s}（下一个交易日 T+1）的走势。\n"
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
        "data_date": data_day_s,
        "target_date": next_day_s,
    }
    return ctx, summary


async def predict_tomorrow(force_refresh: bool = False) -> dict:
    """生成明日（下一个交易日）大盘走势预测。

    缓存按"最近交易日"（data_day）而不是自然日：
    - 周五收盘后生成 → 数据基准周五；周末/盘前访问都命中同一份缓存
    - "明日" = 下一个交易日（自动跳过周末与法定节假日）
    优先返回数据库缓存（跨实例共享），无则生成并写入。
    """
    settings = get_settings()

    # 数据基准日 = 最近交易日（收盘后有完整数据的那天）
    data_day = await trade_calendar_service.last_trading_day()
    today = data_day.isoformat()
    next_day = await trade_calendar_service.next_trading_day(data_day)

    # 1. 数据库缓存（按数据日）
    if not force_refresh:
        db_result = await _load_db_prediction(today)
        if db_result:
            # 兼容旧记录（无日期语义字段）：按当前交易日补齐
            db_result.setdefault("data_date", today)
            if not db_result.get("target_date"):
                db_result["target_date"] = next_day.isoformat()
            _prediction_cache[today] = (dt.datetime.now().isoformat(), db_result)
            return db_result
    # 2. 内存缓存
    if not force_refresh and today in _prediction_cache:
        cached = _prediction_cache[today][1]
        cached.setdefault("data_date", today)
        if not cached.get("target_date"):
            cached["target_date"] = next_day.isoformat()
        return cached

    hist = await asyncio_hist()
    ctx, summary = build_market_context(hist, data_day=data_day, next_day=next_day)

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
        result = rule
    else:
        result = {
            "index": MARKET_NAME,
            "date": hist[-1]["date"],
            "summary": prediction,
            "technical": summary,
            "source": "llm",
        }

    # 统一补齐日期语义字段（LLM 与规则回退两个分支共用）：
    # - date：行情 K 线最后一根的日期（数据源可能滞后一日，仅作参考）
    # - data_date：本份预测的数据基准交易日（缓存 key 也用它）
    # - target_date：本份预测针对的交易日（T+1，跳过周末/节假日）
    result["data_date"] = today
    result["target_date"] = next_day.isoformat()

    # 保存预测记录（用于准确率统计）
    try:
        await save_prediction_record(result, data_date=today, target_date=next_day.isoformat())
    except Exception as e:
        print(f"[prediction] 保存记录失败: {e}")

    # 写入每日缓存（内存 + 数据库）
    _prediction_cache[today] = (dt.datetime.now().isoformat(), result)
    try:
        await _save_db_prediction(today, result)
    except Exception as e:
        print(f"[prediction] 数据库缓存写入失败: {e}")
    return result


async def _load_db_prediction(pred_date: str) -> dict | None:
    """从数据库读取当日预测。"""
    if not supabase_store.is_configured():
        return None
    try:
        sb = await supabase_store.get_service_client()
        res = (
            await sb.table("daily_predictions")
            .select("result")
            .eq("pred_date", pred_date)
            .limit(1)
            .execute()
        )
        if res.data:
            return res.data[0]["result"]
    except Exception as e:
        print(f"[prediction] 数据库读取失败: {e}")
    return None


async def _save_db_prediction(pred_date: str, result: dict) -> None:
    """写入当日预测到数据库（upsert）。"""
    if not supabase_store.is_configured():
        return
    sb = await supabase_store.get_service_client()
    existing = (
        await sb.table("daily_predictions")
        .select("id")
        .eq("pred_date", pred_date)
        .limit(1)
        .execute()
    )
    import json

    payload = {"pred_date": pred_date, "result": result}
    if existing.data:
        await sb.table("daily_predictions").update(payload).eq("id", existing.data[0]["id"]).execute()
    else:
        await sb.table("daily_predictions").insert(payload).execute()


def clear_prediction_cache() -> None:
    """清除缓存。"""
    _prediction_cache.clear()


async def save_prediction_record(pred: dict, data_date: str | None = None, target_date: str | None = None) -> None:
    """将预测结果写入 Supabase prediction_records 表。"""
    if not supabase_store.is_configured():
        return
    s = pred.get("summary", {})
    norm = normalize_direction(str(s.get("direction", "震荡")))
    # target_date：显式传入的下一交易日；否则回退次日（兼容旧逻辑）
    target = target_date or (dt.date.today() + dt.timedelta(days=1)).isoformat()
    try:
        sb = await supabase_store.get_service_client()
        await sb.table("prediction_records").insert(
            {
                "data_date": data_date or dt.date.today().isoformat(),
                "target_date": target,
                "direction": norm,
                "direction_raw": str(s.get("direction", "")),
                "direction_score": s.get("direction_score"),
                "probability": str(s.get("probability", "")),
                "expected_low": (s.get("expected_range") or {}).get("low") if isinstance(s.get("expected_range"), dict) else None,
                "expected_high": (s.get("expected_range") or {}).get("high") if isinstance(s.get("expected_range"), dict) else None,
                "summary": str(s.get("summary", "")),
            }
        ).execute()
    except Exception as e:
        print(f"[prediction] insert error: {e}")


def normalize_direction(raw: str) -> str:
    """将方向描述归一化为 上涨/震荡/下跌。"""
    raw = raw.strip()
    if any(k in raw for k in ("上涨", "涨", "偏多", "强", "看多")):
        return "上涨"
    if any(k in raw for k in ("下跌", "跌", "偏空", "弱", "看空")):
        return "下跌"
    return "震荡"


async def settle_predictions() -> int:
    """结算待结算的预测：按每条记录各自的 target_date 对应实际走势判定。

    交易日对齐：
    - 用最近收盘的交易日（data_day）作为结算基准
    - 结算所有 target_date <= data_day 的未结算预测
    - 每条记录用其 target_date 当日（及其前一交易日）的上证收盘涨跌判定，
      避免漏跑 cron 后所有逾期记录共用"最新一天"行情导致准确率失真
    - 行情数据缺失的记录留待下次结算

    返回本次结算的记录数。
    """
    if not supabase_store.is_configured():
        return 0
    sb = await supabase_store.get_service_client()
    # 最近已收盘交易日
    data_day = await trade_calendar_service.last_trading_day()
    hist = await asyncio_hist()

    # 找未结算的记录（target_date <= 最近交易日，即今天已经"到点"的预测）
    res = await (
        sb.table("prediction_records")
        .select("id", "direction", "target_date")
        .is_("settled_at", "null")
        .lte("target_date", data_day.isoformat())
        .execute()
    )
    rows = res.data
    if not rows:
        return 0

    # date -> (当日收盘, 前一交易日收盘)
    by_date: dict[str, tuple[float, float]] = {}
    for i in range(1, len(hist)):
        by_date[str(hist[i]["date"])[:10]] = (hist[i]["close"], hist[i - 1]["close"])

    settled = 0
    settled_at = dt.datetime.now(dt.timezone.utc).isoformat()
    for row in rows:
        tgt = str(row.get("target_date", ""))[:10]
        pair = by_date.get(tgt)
        if not pair or not pair[1]:
            continue  # 该日行情缺失，留待下次
        close, prev_close = pair
        actual_change = (close / prev_close - 1) * 100
        actual_dir = "上涨" if actual_change >= 0.2 else ("下跌" if actual_change <= -0.2 else "震荡")
        hit = row["direction"] == actual_dir
        await (
            sb.table("prediction_records")
            .update(
                {
                    "actual_change": round(actual_change, 2),
                    "actual_direction": actual_dir,
                    "hit": hit,
                    "settled_at": settled_at,
                }
            )
            .eq("id", row["id"])
            .execute()
        )
        settled += 1
    return settled


async def get_prediction_stats() -> dict:
    """统计历史预测准确率。"""
    if not supabase_store.is_configured():
        return {"total": 0, "settled": 0, "hit": 0, "hit_rate": None, "by_direction": {}}
    sb = await supabase_store.get_service_client()
    res = await (
        sb.table("prediction_records")
        .select("direction", "hit")
        .not_.is_("settled_at", None)
        .execute()
    )
    rows = res.data
    total = len(rows)
    hit = sum(1 for r in rows if r.get("hit"))
    by_direction: dict = {}
    for r in rows:
        d = r.get("direction", "未知")
        b = by_direction.setdefault(d, {"total": 0, "hit": 0})
        b["total"] += 1
        if r.get("hit"):
            b["hit"] += 1
    for d, b in by_direction.items():
        b["hit_rate"] = round(b["hit"] / b["total"] * 100, 1) if b["total"] else None
    return {
        "total": total,
        "settled": total,
        "hit": hit,
        "hit_rate": round(hit / total * 100, 1) if total else None,
        "by_direction": by_direction,
    }


async def get_prediction_history(limit: int = 30) -> list[dict]:
    """历史预测记录（含结算结果）。"""
    if not supabase_store.is_configured():
        return []
    sb = await supabase_store.get_service_client()
    res = await (
        sb.table("prediction_records")
        .select("*")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return res.data


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
