"""明日大盘推衍：市场状态 + 市场宽度 + 技术信号 + LLM 解释，生成次日走势预判。

方向分的产生方式（这是本模块的核心契约）：

    evidence_score = regime_score(HMM 市场状态) + 市场宽度修正
    raw_score      = 0.7 × evidence_score + 0.3 × LLM 分   （LLM 单独影响力限 ±0.5）
    direction_score= apply_inertia(raw_score, 昨日方向分)   （禁止单日跳变 > 1.0）
    direction      = score_to_direction(direction_score)

设计意图：**方向由量化证据决定，LLM 只负责解释与有限微调**。
原来的实现是反过来的（LLM 直接给方向、规则兜底），单次采样 + 窄证据面
导致同一个市场状态下方向每天摆动。

结算口径与展示口径统一走 ``direction_score``，不再出现「展示震荡偏强、
结算按上涨算」这类不一致。
"""
from __future__ import annotations

import asyncio
import datetime as dt
import math

import akshare as ak
from openai import AsyncOpenAI

from app.config import get_settings
from app.services import (
    akshare_guard,
    regime_service,
    signal_service,
    supabase_store,
    trade_calendar_service,
)
from app.services.cache_utils import put_bounded

MARKET_INDEX = "sh000001"
MARKET_NAME = "上证指数"

# 判涨/判跌的中性带宽（%）：日涨跌幅落在这个区间内算「震荡」。
#
# 原值是 0.2%，太窄 —— 实际结算时「震荡」几乎不出现，而模型有约 1/3 的概率
# 预测震荡，标签空间严重不匹配（预测震荡几乎必然判错，胜率因此失真）。
# 放宽到 0.5% 后与 regime_service.SCORE_UP / SCORE_DOWN 的三分类阈值对齐。
# 注意：本次调整之前落库的历史记录仍按 0.2% 结算，跨口径比较胜率时需留意。
DIRECTION_FLAT_BAND_PCT = 0.5

# 每日大盘推衍缓存：key=日期，value=(生成时间, data)。一天只跑一次。
_prediction_cache: dict[str, tuple[str, dict]] = {}
_PREDICTION_CACHE_MAX = 7

PREDICTION_SYSTEM_PROMPT = """你是一位擅长 A 股大盘研判的资深策略分析师，风格类似同花顺/指南针的收盘复盘研报。基于用户提供的上证指数【最新交易日收盘后】技术数据与【市场宽度】数据，研判【下一个交易日】的走势。

【核心概念：交易日（T 日）】
- A 股只在交易日开盘（周一至周五，法定节假日休市）
- 你收到的数据是最近一个已收盘交易日（记为 T）的收盘数据
- 你要预测的是 T 之后的下一个交易日（T+1）
- 如果 T 是周五，T+1 就是下周一，中间周末不预测

【关键：方向不是由你定的】
输入中已经给出系统量化证据分（市场状态分 + 市场宽度分 → 证据分，0~10）。
- 方向标签（上涨/震荡/下跌）**完全由证据分决定，你无法改变它**，你只需读懂并解释它
- 你的 direction_score 只影响「方向分的强弱」，权重 0.3，影响力**上限 ±0.5 分**：
  5.0 = 不改变系统结论（默认值）· 3.3~6.7 按 0.3 权重线性生效 · 超出 6.7 或低于 3.3 的部分直接截断
- 所以：**除非你发现了证据分没有覆盖的重大信息，否则 direction_score 请直接填 5.0**
- direction 字段请**照抄**输入中「系统量化结论」给出的方向标签，不要自行改写
- 你的主要价值在于**解释与风险条件**（summary / drivers / trading_advice），而不是争夺方向

【输出要求】
只输出一个合法 JSON 对象，不要任何其他文字。结构如下：

{
  "direction": "照抄系统量化结论给出的方向标签",
  "direction_score": 0到10的小数，5.0=不改变系统结论（默认值），3.3~6.7=轻微倾向,
  "expected_range": {"low": 预计最低点位, "high": 预计最高点位},
  "probability": "各方向概率，如：上涨40%/震荡35%/下跌25%",
  "key_levels": {"support1": "第一支撑", "support2": "第二支撑", "resistance1": "第一压力", "resistance2": "第二压力"},
  "summary": "120字以内的下一个交易日走势研判，先结论后逻辑，句式像专业复盘报告",
  "drivers": ["2-4条影响下一个交易日走势的关键因素"],
  "trading_advice": "给散户的操作建议，含建议仓位、关注板块、风险提示"
}

【分析维度】
- 市场状态：输入已给出状态（上行/震荡/下行）、状态分、状态自转移概率与期望持续时间 ——
  自转移概率高说明状态粘性强，下一个交易日大概率延续，不要因为单日小波动就推翻它
- 市场宽度：涨跌家数比、涨停/跌停家数、全市场成交额环比 —— 判断是普涨普跌还是结构性行情
- 技术面：均线排列（现价在 MA20/MA60 之上还是之下、两条均线的相对位置）、
  现价与主支撑/主压力的距离、布林带位置、量价是否配合
- 位置与空间：指数处于近期 60 日区间的高位还是低位，距离支撑/压力位的空间
- 情绪与节奏：结合当日涨跌幅、量比、多窗口动量一致度判断市场情绪强弱
- 多空博弈：结合关键点位给出多空分水岭

【关于 RSI 与量比的硬性约束（重要）】
- RSI 与量比是**读数**，不参与证据分计算。给出它们的数值是为了让你解释得更具体，
  **不是**让你用它们推翻证据分。
- **禁止把「RSI 超卖」当作看多理由**，也禁止把「RSI 超买」当作看空理由并据此改变方向倾向。
  A 股指数在下跌趋势中长期处于低 RSI 是常态，低 RSI 不等于「该反弹了」；
  同理高 RSI 不等于「该回调了」。若你的判断与证据分冲突，**以证据分为准**。
- 引用这些读数时只描述事实（"RSI(14) 为 34.9，处于近月低位"），
  不要延伸成方向结论（"因此超卖反弹可期"）。
- 不得提到输入中未给出的指标（例如 MACD、KDJ），也不得编造任何数值。
【写作风格】
- summary 要像专业股评：先给结论方向，再用数据支撑逻辑，避免空话套话
- drivers 要具体可验证（状态/宽度/技术信号/量能/位置），不要泛泛而谈
【注意】
- 仅基于提供的数据研判，数据不足时如实说明，绝不编造
- 预测仅供研究参考，不构成投资建议"""


def get_index_history(days: int = 180) -> list[dict]:
    """获取上证指数历史K线。"""
    df = akshare_guard.call(ak.stock_zh_index_daily, symbol=MARKET_INDEX)
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


def _pos_word(price: float, ma: float) -> str:
    """现价相对均线的方位词：供 prompt 描述多空排列。

    提出成函数是因为「之上/之下」必须在两处（MA20/MA60）保持一致口径，
    并在差值为 0 时不给出错误方向。
    """
    delta = price - ma
    if delta > 0:
        return f"之上（+{delta / ma * 100:.2f}%）"
    if delta < 0:
        return f"之下（{delta / ma * 100:.2f}%）"
    return "同价"


def build_market_context(
    hist: list[dict],
    data_day: dt.date | None = None,
    next_day: dt.date | None = None,
    breadth: dict | None = None,
) -> tuple[str, dict]:
    """组装指数上下文 + 技术信号 + 市场状态 + 市场宽度 + 交易日信息。

    breadth 由 ``regime_service.fetch_breadth()`` 提供（需要网络），为 None 时
    只影响宽度维度的证据，状态分照常参与合成。
    """
    closes = [h["close"] for h in hist]
    volumes = [h["volume"] for h in hist]
    last = hist[-1]
    price = last["close"]

    sig = signal_service.compute_signals(closes, price)

    # 市场状态（HMM 优先）：用后验概率对各状态基准分加权 → 连续状态分，自带惯性
    regime = regime_service.compute_regime(closes, volumes)
    breadth_score = (breadth or {}).get("breadth_score") if breadth else None
    evidence_score = regime_service.blend_evidence(regime.get("regime_score"), breadth_score)

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
        # 均线必须带「在现价之上/之下」的方位，否则模型无法判断多头/空头排列；
        # 布林轨必须标明哪个是支撑哪个是压力，否则模型只能猜（曾把下轨猜成支撑）。
        ctx += (
            f"技术信号：\n"
            f"  支撑位 {sig['support']}（现价下方最近的支撑，跌破视为转弱）\n"
            f"  压力位 {sig['resistance']}（现价上方最近的压力，突破视为转强）\n"
            f"  均线：MA5 {sig['ma5']}，MA20 {sig['ma20']}，MA60 {sig['ma60']}"
            f"（现价 {price:.2f} 位于 MA20 {_pos_word(price, sig['ma20'])}、"
            f"MA60 {_pos_word(price, sig['ma60'])}）\n"
            f"  布林带(20,2)：下轨 {sig['bb_lower']}（支撑参考，非主支撑）、"
            f"上轨 {sig['bb_upper']}（压力参考，非主压力）\n"
            f"  信号强度 {sig['strength']}/10\n"
        )
    # RSI 与量比是**读数**不是打分项（见 regime_service._rule_regime）：这里如实给出数值，
    # 并说明它们不参与方向分，避免模型把「超卖」当成看多理由去对抗证据分。
    readings = regime.get("readings") or {}
    if readings:
        ctx += (
            f"技术读数（仅作解释参考，不参与方向分）："
            f"RSI(14) {readings.get('rsi14', '-')}，"
            f"20日动量 {readings.get('ret20_pct', '-')}%，"
            f"5日动量 {readings.get('ret5_pct', '-')}%，"
            f"多窗口动量一致度 {readings.get('mom_agreement', '-')}"
            f"（1.0=四个时间窗口一致看多，-1.0=一致看空，0=方向打架）\n"
        )
    ctx += f"近5日收盘：{', '.join(f'{c:.0f}' for c in closes[-5:])}\n"
    ctx += _quantitative_block(breadth, regime, evidence_score)

    summary = {
        "price": price,
        "day_change": round(day_change, 2),
        "vol_ratio": round(vol_ratio, 2),
        "ret5": round(ret5, 2),
        "ret20": round(ret20, 2),
        "position_60d": round(pos, 1),
        "signal": sig,
        "regime": regime,
        "breadth": breadth,
        "evidence_score": evidence_score,
        "data_date": data_day_s,
        "target_date": next_day_s,
    }
    return ctx, summary


def _quantitative_block(breadth: dict | None, regime: dict, evidence_score: float) -> str:
    """组装「系统量化结论」文本：市场状态 + 状态稳定性 + 市场宽度 + 证据分锚点。

    这一段是给 LLM 的**约束条件**，不是参考信息 —— prompt 里已明确它只做 ±0.5 微调，
    这里把锚点摆到它眼前，避免它凭想象另起一套方向。
    """
    lines = [
        f"【系统量化结论】市场状态「{regime.get('state', '未知')}」"
        f"（方法 {regime.get('method', '-')}），状态分 {regime.get('regime_score', '-')}/10，"
        f"证据分 {evidence_score}/10（0-10，>6.2 判上涨、<3.8 判下跌、其间为震荡）"
    ]

    probs = regime.get("state_probs") or {}
    if probs:
        lines.append("状态概率：" + "，".join(f"{key} {val:.0%}" for key, val in probs.items()))
    if regime.get("state_persistence") is not None:
        duration = regime.get("expected_duration")
        if duration:
            lines.append(
                f"状态粘性：当前状态自转移概率 {regime['state_persistence']}，"
                f"期望维持约 {duration} 个交易日（不要因为单日小波动就推翻该状态）"
            )
        else:
            lines.append(
                f"状态粘性：当前状态自转移概率 {regime['state_persistence']}"
                "（样本区间内该状态未被打破，倾向于延续）"
            )
    features = regime.get("features") or {}
    if features:
        lines.append(
            "状态特征："
            + "，".join(f"{key} {val}" for key, val in features.items())
        )

    if breadth:
        parts = [
            f"上涨 {breadth.get('up_count')} 家 / 下跌 {breadth.get('down_count')} 家"
            f"（上涨占比 {float(breadth.get('up_down_ratio') or 0) * 100:.1f}%）",
            f"涨停 {breadth.get('limit_up_count')} 家 / 跌停 {breadth.get('limit_down_count')} 家",
            f"全市场成交额 {float(breadth.get('total_amount_yi') or 0):.0f} 亿",
        ]
        if breadth.get("amount_change_pct") is not None:
            parts.append(f"成交额环比 {float(breadth['amount_change_pct']):+.1f}%")
        lines.append("市场宽度：" + "，".join(parts) + f"（宽度分 {breadth.get('breadth_score')}/10）")
    else:
        lines.append("市场宽度：数据暂不可用（不影响状态分结论）")

    if regime.get("note"):
        lines.append(f"状态识别备注：{regime['note']}")
    return "\n".join(lines) + "\n"


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
            put_bounded(_prediction_cache, today, (dt.datetime.now().isoformat(), db_result), max_entries=_PREDICTION_CACHE_MAX)
            return db_result
    # 2. 内存缓存
    if not force_refresh and today in _prediction_cache:
        cached = _prediction_cache[today][1]
        cached.setdefault("data_date", today)
        if not cached.get("target_date"):
            cached["target_date"] = next_day.isoformat()
        return cached

    hist = await asyncio_hist()

    # 上一交易日快照：既给方向分提供「昨日锚」（惯性平滑），也提供成交额环比的基期
    prev_result = await _load_prev_snapshot(today)
    breadth = await regime_service.fetch_breadth(prev_amount_yi=_prev_amount_yi(prev_result))

    ctx, summary = build_market_context(
        hist, data_day=data_day, next_day=next_day, breadth=breadth
    )

    llm_score: float | None = None
    if not settings.deepseek_api_key:
        # 未配置 LLM：方向完全由量化证据分（状态 + 宽度）决定
        result = _rule_based_prediction(summary)
    else:
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

        prediction: dict = {}
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
            result = _rule_based_prediction(summary, note="LLM 预测输出异常，已回退规则预判。")
        else:
            result = {
                "index": MARKET_NAME,
                "date": hist[-1]["date"],
                "summary": prediction,
                "technical": summary,
                "source": "llm",
            }
            # LLM 只提供「相对中性的微调量」，最终方向仍由证据分主导
            llm_score = _to_float(prediction.get("direction_score"))

    if not result.get("date"):
        result["date"] = hist[-1]["date"]
    # 统一合成方向（LLM / 规则两个分支共用同一套口径与惯性约束）
    _finalize_direction(result, summary, prev_result, llm_score=llm_score)

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
    put_bounded(_prediction_cache, today, (dt.datetime.now().isoformat(), result), max_entries=_PREDICTION_CACHE_MAX)
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


def _to_float(value) -> float | None:
    """安全转 float：脏数据一律当缺失，不抛异常。"""
    try:
        if value is None:
            return None
        out = float(value)
        return out if math.isfinite(out) else None
    except (TypeError, ValueError):
        return None


async def _load_prev_snapshot(current_data_day: str) -> dict | None:
    """读取「上一交易日」的完整预测快照。

    用途有两个：给方向分提供昨日锚（惯性平滑）、给成交额环比提供基期。
    优先数据库（跨实例共享），未配置/失败时回退内存缓存；都没有则返回 None ——
    此时不做平滑，等价于冷启动第一天。
    """
    if supabase_store.is_configured():
        try:
            sb = await supabase_store.get_service_client()
            res = (
                await sb.table("daily_predictions")
                .select("pred_date", "result")
                .lt("pred_date", current_data_day)
                .order("pred_date", desc=True)
                .limit(1)
                .execute()
            )
            if res.data:
                return res.data[0].get("result")
        except Exception as e:
            print(f"[prediction] 读取上一交易日快照失败: {e}")

    keys = [key for key in _prediction_cache if key < current_data_day]
    if keys:
        return _prediction_cache[max(keys)][1]
    return None


def _prev_amount_yi(prev_result: dict | None) -> float | None:
    """上一交易日全市场成交额（亿），缺失返回 None（宽度环比维度自动不计分）。"""
    if not prev_result:
        return None
    technical = prev_result.get("technical") or {}
    breadth = technical.get("breadth") or {}
    return _to_float(breadth.get("total_amount_yi"))


def _prev_direction_score(prev_result: dict | None) -> float | None:
    """上一交易日的最终方向分（惯性锚点）。"""
    if not prev_result:
        return None
    return _to_float((prev_result.get("summary") or {}).get("direction_score"))


def _finalize_direction(
    result: dict,
    summary: dict,
    prev_result: dict | None,
    llm_score: float | None = None,
) -> None:
    """统一合成最终方向标签与方向分，并写回 result["summary"]。

    这是全系统方向的**唯一出口**，结算、展示、仓位三处口径都取自这里。
    具体合成规则见 ``regime_service.resolve_direction``，要点：
      direction   = score_to_direction(证据分)                    ← LLM 与惯性都改不了
      raw_score   = 证据分 + LLM 微调（LLM 权重 0.3、上限 ±0.5）
      final_score = 夹到标签分数带(惯性平滑(raw_score, 昨日分))     ← 禁止单日跳变 > 1.0

    同时把中间量写进 ``summary.direction_model``，供前端/排查复核方向是怎么来的。
    """
    s = result.setdefault("summary", {})
    regime = summary.get("regime") or {}
    breadth = summary.get("breadth") or {}
    evidence = _to_float(summary.get("evidence_score"))
    if evidence is None:
        evidence = regime_service.NEUTRAL_SCORE

    # 保留 LLM 的原始方向文案（供历史记录 `direction_raw` 展示），
    # 但对外方向标签只认分数，不认文案。
    llm_direction = str(s.get("direction") or "").strip() if result.get("source") == "llm" else None

    prev_score = _prev_direction_score(prev_result)
    direction, final_score = regime_service.resolve_direction(evidence, llm_score, prev_score)

    s["direction"] = direction
    s["direction_score"] = final_score
    s["llm_direction"] = llm_direction or None
    s["direction_model"] = {
        "evidence_score": round(evidence, 2),
        "regime_state": regime.get("state"),
        "regime_score": regime.get("regime_score"),
        "regime_method": regime.get("method"),
        "breadth_score": breadth.get("breadth_score"),
        "llm_score": llm_score,
        "llm_direction": llm_direction or None,
        "llm_contribution": regime_service.llm_contribution(llm_score),
        "raw_score": regime_service.blend_direction_score(evidence, llm_score),
        "prev_score": prev_score,
        "final_score": final_score,
    }


async def save_prediction_record(pred: dict, data_date: str | None = None, target_date: str | None = None) -> None:
    """将预测结果写入 Supabase prediction_records 表。"""
    if not supabase_store.is_configured():
        return
    s = pred.get("summary", {})
    norm = normalize_direction(str(s.get("direction", "震荡")))
    # direction_raw 存最终方向标签（与结算口径一致，避免历史表里展示的方向与结算方向打架）；
    # LLM 的原始文案留在 daily_predictions 快照的 summary.direction_model.llm_direction 里备查。
    raw_direction = str(s.get("direction", ""))
    # target_date：显式传入的下一交易日；否则回退次日（兼容旧逻辑）
    target = target_date or (dt.date.today() + dt.timedelta(days=1)).isoformat()
    try:
        sb = await supabase_store.get_service_client()
        await sb.table("prediction_records").insert(
            {
                "data_date": data_date or dt.date.today().isoformat(),
                "target_date": target,
                "direction": norm,
                "direction_raw": raw_direction,
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
    """将方向**文案**归一化为 上涨/震荡/下跌。

    **先判「震荡」**：「震荡偏强」「弱势震荡」「横盘整理」这类描述带方向倾向词，
    但本质仍是区间震荡。按倾向词优先匹配会误归成单边方向
    （历史 bug：「震荡偏强」含「强」被判成上涨，与结算口径矛盾，胜率统计因此失真）。

    注意：这只是解析 LLM 原始文案的兜底工具。对外方向标签以
    ``regime_service.score_to_direction(direction_score)`` 为准 —— 由分数决定，不由文案决定。
    """
    raw = raw.strip()
    if any(k in raw for k in ("震荡", "横盘", "盘整", "整理", "中性", "胶着", "反复")):
        return "震荡"
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
        # 判涨/判跌的中性带宽度与方向标签阈值对齐（见 DIRECTION_FLAT_BAND_PCT 说明）
        if actual_change >= DIRECTION_FLAT_BAND_PCT:
            actual_dir = "上涨"
        elif actual_change <= -DIRECTION_FLAT_BAND_PCT:
            actual_dir = "下跌"
        else:
            actual_dir = "震荡"
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


def _rule_based_prediction(summary: dict, note: str | None = None) -> dict:
    """无 LLM（或 LLM 输出异常）时的规则预判。

    这里**不再自造方向分**：方向分统一由 ``_finalize_direction`` 从证据分合成，
    本函数只负责文案、关键点位与驱动因素。旧实现用 ``信号强度/近5日涨幅`` 直接
    切出方向与分数，与 LLM 路径各说各话，是方向口径分裂的来源之一。
    """
    sig = summary.get("signal") or {}
    regime = summary.get("regime") or {}
    breadth = summary.get("breadth") or {}
    price = summary["price"]
    ret5 = summary.get("ret5", 0)
    evidence = summary.get("evidence_score")
    state = regime.get("state", "未知")

    if breadth:
        breadth_txt = (
            f"涨跌家数 {breadth.get('up_count')}/{breadth.get('down_count')}、"
            f"涨停 {breadth.get('limit_up_count')} 家、"
            f"成交额 {float(breadth.get('total_amount_yi') or 0):.0f} 亿"
        )
        breadth_bullet = (
            f"市场宽度：上涨占比 {float(breadth.get('up_down_ratio') or 0) * 100:.1f}%、"
            f"涨停 {breadth.get('limit_up_count')} 家 / 跌停 {breadth.get('limit_down_count')} 家"
        )
    else:
        breadth_txt = "市场宽度数据缺失"
        breadth_bullet = "市场宽度：数据缺失，未计入证据"

    text = (
        f"量化预判：市场状态「{state}」（状态分 {regime.get('regime_score', '-')}/10），"
        f"证据分 {evidence}/10；{breadth_txt}；近5日指数 {ret5:+.2f}%。"
        f"方向完全由状态与市场宽度证据决定，未叠加主观判断。"
    )

    return {
        "index": MARKET_NAME,
        "date": "",
        "summary": {
            # direction / direction_score 仅为占位，_finalize_direction 会统一覆盖
            "direction": "震荡",
            "direction_score": regime_service.NEUTRAL_SCORE,
            "expected_range": {
                "low": round(sig.get("support", price * 0.99), 0),
                "high": round(sig.get("resistance", price * 1.01), 0),
            },
            "probability": "规则模式：未做概率研判",
            "key_levels": {
                "support1": sig.get("support"),
                "resistance1": sig.get("resistance"),
            },
            "summary": (f"{note}{text}" if note else text),
            "drivers": [
                f"市场状态：{state}（状态分 {regime.get('regime_score', '-')}/10，方法 {regime.get('method', '-')}）",
                breadth_bullet,
                f"技术信号强度 {sig.get('strength', '-')}，支撑 {sig.get('support', '-')} / 压力 {sig.get('resistance', '-')}",
            ],
            "trading_advice": "规则模式：仓位跟随证据分与市场状态，配置 LLM 后可获得更详细研判",
        },
        "technical": summary,
        "source": "rule",
    }
