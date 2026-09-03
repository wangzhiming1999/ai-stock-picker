"""每日收盘推荐：策略扫描候选 + LLM 精选 10 只并给出推荐理由。"""
from __future__ import annotations

import datetime as dt
import json

from openai import AsyncOpenAI

from app.config import get_settings
from app.routes import market as market_routes
from app.services import supabase_store, trade_calendar_service

# 每日推荐缓存：key=日期，value=(生成时间, data)。一天只跑一次。
_recommendation_cache: dict[str, tuple[str, dict]] = {}

RECOMMEND_SYSTEM_PROMPT = """你是一位资深的 A 股投资顾问，类似同花顺/指南针的"明日机会股"专栏主编，擅长从候选股票中挑选下一个交易日最值得关注的标的。

【交易日语义】
- 候选数据基于最近一个已收盘交易日（交易日 T）收盘
- "明日关注"指下一个交易日（T+1），需要跳过周末/节假日
- 你的推荐是"T+1 日可跟踪观察"的清单，不是让用户盲目追高

【任务】
从用户提供的候选股票（含行情与技术信号）中，挑选 10 只最值得下一个交易日关注的股票，并为每只给出具体推荐理由。

【输出要求】
只输出一个合法的 JSON 数组，不要任何其他文字。格式如下：

[
  {
    "code": "600519",
    "name": "贵州茅台",
    "reason": "80字以内的推荐理由，像专业股评：先说关注逻辑（技术形态/量能/催化剂），再给 T+1 日观察要点（如：回踩不破XX可关注、放量突破XX转强），结合提供的行情/技术数据",
    "confidence": 0到10的置信分
  },
  ...
]

【挑选原则】
- 优先技术形态健康、量能配合、估值合理，且 T+1 日有明确观察点的标的
- 兼顾不同风格（动量/趋势/低估值/放量），不要全部集中一个方向
- 排除有明显风险信号（如已大幅上涨追高风险、停牌、ST）的标的
- 理由要具体，引用候选数据中的价格/涨跌幅/信号/压力位支撑位，不要空话
- 强调"T+1 日可跟踪观察"而非"盲目买入"，给出触发/止损的观察条件
- 仅供研究参考，不构成投资建议"""


def clear_recommendation_cache() -> None:
    """清除缓存（用于测试或强制刷新场景）。"""
    _recommendation_cache.clear()


async def generate_daily_recommendations(force_refresh: bool = False) -> dict:
    """生成每日收盘推荐：跑四个策略 → 合并候选 → LLM 精选 10 只。

    缓存按"最近交易日"（data_day）而不是自然日：
    - 同一交易日的收盘后推荐，盘前/周末访问都命中同一份缓存
    - 不会因自然日切换而重复生成或读错数据
    优先返回数据库当日缓存（跨实例共享），无则生成并写入。
    """
    data_day = await trade_calendar_service.last_trading_day()
    today = data_day.isoformat()
    target_day = (await trade_calendar_service.next_trading_day(data_day)).isoformat()

    def _with_target(result: dict) -> dict:
        result.setdefault("target_date", target_day)
        return result

    # 1. 数据库缓存（按数据日）
    if not force_refresh:
        db_result = await _load_db_recommendation(today)
        if db_result:
            db_result = _with_target(db_result)
            _recommendation_cache[today] = (dt.datetime.now().isoformat(), db_result)
            return db_result
    # 2. 内存缓存
    if not force_refresh and today in _recommendation_cache:
        return _with_target(_recommendation_cache[today][1])

    settings = get_settings()
    candidates: dict[str, dict] = {}

    # 1. 跑四个策略收集候选
    for strategy in ("momentum", "trend", "value", "volume"):
        try:
            results = await _scan_strategy(strategy, force=force_refresh)
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
        result = {"date": today, "target_date": target_day, "source": "empty", "recommendations": [], "candidates": 0, "message": "没有找到合适的候选股票（可能是非交易日或盘前）"}
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
        "target_date": target_day,
        "source": source,
        "recommendations": recs,
        "candidates": len(ranked),
    }
    _recommendation_cache[today] = (dt.datetime.now().isoformat(), result)

    # 保存推荐记录（胜率跟踪 + 当日缓存持久化）
    try:
        await save_recommendations(today, recs)
        await _save_db_recommendation(today, result)
    except Exception as e:
        print(f"[recommend] 保存推荐记录失败: {e}")

    return result


async def _load_db_recommendation(rec_date: str) -> dict | None:
    """从数据库读取当日推荐结果（整组快照）。"""
    if not supabase_store.is_configured():
        return None
    try:
        sb = await supabase_store.get_service_client()
        res = (
            await sb.table("daily_recommend_snapshots")
            .select("result")
            .eq("rec_date", rec_date)
            .limit(1)
            .execute()
        )
        if res.data:
            return res.data[0]["result"]
    except Exception as e:
        print(f"[recommend] 数据库读取失败: {e}")
    return None


async def _save_db_recommendation(rec_date: str, result: dict) -> None:
    """写入当日推荐结果到数据库（upsert）。"""
    if not supabase_store.is_configured():
        return
    sb = await supabase_store.get_service_client()
    existing = (
        await sb.table("daily_recommend_snapshots")
        .select("id")
        .eq("rec_date", rec_date)
        .limit(1)
        .execute()
    )
    payload = {"rec_date": rec_date, "result": result}
    if existing.data:
        await sb.table("daily_recommend_snapshots").update(payload).eq("id", existing.data[0]["id"]).execute()
    else:
        await sb.table("daily_recommend_snapshots").insert(payload).execute()


async def save_recommendations(rec_date: str, recs: list[dict]) -> None:
    """将当日推荐写入 Supabase daily_recommendations 表（幂等）。"""
    if not supabase_store.is_configured() or not recs:
        return
    sb = await supabase_store.get_service_client()
    # 先检查当日是否已保存，避免重复
    existing = (
        await sb.table("daily_recommendations")
        .select("id")
        .eq("rec_date", rec_date)
        .limit(1)
        .execute()
    )
    if existing.data:
        return
    rows = [
        {
            "rec_date": rec_date,
            "code": r["code"],
            "name": r["name"],
            "recommend_price": r["price"],
            "reason": r.get("reason", ""),
            "confidence": r.get("confidence"),
            "source": "llm" if r.get("reason") and "策略分" not in r.get("reason", "") else "rule",
        }
        for r in recs
    ]
    await sb.table("daily_recommendations").insert(rows).execute()


async def _scan_strategy(strategy: str, force: bool = False) -> list[dict]:
    """对指定策略跑一次扫描（复用市场路由的逻辑）。force 时穿透行情快照缓存。"""
    from app.services import data_service

    spot = await market_routes._get_spot(force=force)
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
