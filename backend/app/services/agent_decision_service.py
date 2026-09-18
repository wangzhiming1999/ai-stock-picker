"""Agent 决策记录（TradingAgents 执行闭环）。

定位：给 agent 的交易员计划建 track record —— 四层链路（分析师 → 辩论 → 交易员 → 终审）
此前「跑完即散」，没有一行数据记录「agent 说买 → 实际结果如何」。本服务是唯一的读写口：
  - 落库：深度分析产出终审结论时自动落对照行（rejected/ignored），用户一键采纳时更新为 adopted；
  - 结算：到期日由每日 cron 按收盘价结算 pnl/hit，并生成一段代码模板反思（不额外调 LLM）；
  - 记忆：同票重分析时取最近已结算决策，拼装「上次计划 + 实际偏差 + 反思」注入 LLM 上下文。

降级纪律：**表未建 / Supabase 未配置时一切函数静默降级**（返回 None / 空列表 / False），
绝不影响主分析链路 —— 与 market_spot_cache 同一套可选迁移策略（schema v9）。

证据纪律：结算后的「命中率」走 calibers 的 `agent_plan` 口径（见 calibers.py），
展示层必须随数据下发 caliber，禁止裸百分比。
"""
from __future__ import annotations

import datetime as dt

from app.models import FundManagerVerdict, TradePlan
from app.services import calibers, supabase_store

# 结算窗口默认值：持有 5 个交易日后按收盘价结算。
# 刻意不做长窗口 —— 免费行情源逐日回溯压力大，且窗口越长归因越难（中间任何消息面都会污染结论）。
DEFAULT_HORIZON = 5

_TABLE = "agent_decisions"

# 方向语义：哪些动作是「看多计划」（结算时 settle > entry 记命中）
_BULL_ACTIONS = {"buy", "add"}


async def _get_sb():
    """拿 service client；未配置返回 None（调用方据此降级）。"""
    if not supabase_store.is_configured():
        return None
    try:
        return await supabase_store.get_service_client()
    except Exception:
        return None


def _today() -> dt.date:
    return dt.date.today()


def _plan_row(
    *,
    code: str,
    name: str,
    data_date: str,
    plan: TradePlan,
    verdict: FundManagerVerdict | None,
    status: str,
    user_id: str | None = None,
    horizon: int = DEFAULT_HORIZON,
) -> dict:
    """把 TradePlan + 终审结论收敛成一行 agent_decisions。"""
    v = verdict.decision if verdict else "rejected"
    final_pct = verdict.final_position_pct if verdict else 0.0
    return {
        "user_id": user_id,
        "code": code,
        "name": name,
        "data_date": data_date,
        "action": plan.action,
        "verdict": v,
        "entry_price": plan.entry_price,
        "stop_price": plan.stop_price,
        "target_price": plan.target_price,
        "position_pct": float(final_pct or 0.0),
        "horizon_days": horizon,
        "status": status,
    }


def reflection_from(row: dict, settle_price: float, hit: bool | None = None) -> str:
    """结算后生成一段反思（代码模板，不额外调 LLM）。

    hit 由结算方算好传入（row 在结算时点还没有 hit 字段）。
    只陈述事实与偏差，不下「下次应该怎样」的指令 —— 反思的正确性同样没有回测支撑，
    让 LLM 在下次分析时自己结合新数据解读，而不是被一段老结论牵着走。
    """
    entry = row.get("entry_price")
    if not entry:
        return ""
    pnl_pct = (settle_price / float(entry) - 1) * 100
    direction = "上涨" if pnl_pct >= 0 else "下跌"
    action = row.get("action", "")
    verdict = row.get("verdict", "")
    stop = row.get("stop_price")
    stop_part = f"，计划止损 {stop}" if stop else ""
    tgt = row.get("target_price")
    tgt_part = f"，计划目标 {tgt}" if tgt else ""
    if hit:
        head = "方向与计划一致"
    elif hit is None:
        head = "无方向基准（计划未给出入场价）"
    else:
        head = "方向与计划相反"
    return (
        f"[{row.get('data_date', '')} 决策回顾] 当时（终审 {verdict}）{action} {row.get('code', '')}，"
        f"入场 {entry}{stop_part}{tgt_part}，持有 {row.get('horizon_days', DEFAULT_HORIZON)} 个交易日后"
        f"收盘 {settle_price}，实际{direction} {abs(pnl_pct):.1f}%，{head}。"
        "请把这次结果作为背景之一（不是依据），重新评估当前资料。"
    )


async def record_from_analysis(
    *,
    code: str,
    name: str,
    data_date: str,
    plan: TradePlan,
    verdict: FundManagerVerdict | None,
    user_id: str | None = None,
) -> int | None:
    """深度分析产出终审结论后自动落一行对照记录，返回新行 id（失败/未建表返回 None）。

    - verdict=rejected → status='rejected'（终审否决的对照样本，无需用户动作）；
    - 其余 → status='ignored'（等用户一键采纳，或到期后作为「未采纳对照组」结算）。
    失败静默（返回 None），绝不影响分析主链路。
    """
    sb = await _get_sb()
    if sb is None:
        return None
    try:
        status = "rejected" if (verdict and verdict.decision == "rejected") else "ignored"
        row = _plan_row(
            code=code, name=name, data_date=data_date, plan=plan, verdict=verdict, status=status, user_id=user_id
        )
        res = await sb.table(_TABLE).insert(row).execute()
        if res.data and isinstance(res.data[0], dict):
            return int(res.data[0]["id"])
        return None
    except Exception as e:
        print(f"[agent_decisions] 落库失败 {code}: {type(e).__name__}: {e}")
        return None


async def adopt(
    decision_id: int,
    *,
    user_id: str,
    shares: int,
    sim_trade_id: int | None = None,
) -> dict | None:
    """用户一键采纳：把 ignored 行改成 adopted 并回填关联成交。返回更新后的行。"""
    sb = await _get_sb()
    if sb is None:
        return None
    try:
        res = (
            await sb.table(_TABLE)
            .update({"status": "adopted", "sim_trade_id": sim_trade_id})
            .eq("id", int(decision_id))
            .eq("user_id", user_id)  # RLS 之外的第二道防线：只能采纳自己的决策
            .eq("status", "ignored")
            .select("*")
            .execute()
        )
        return res.data[0] if res.data else None
    except Exception as e:
        print(f"[agent_decisions] 采纳失败 id={decision_id}: {type(e).__name__}: {e}")
        return None


async def latest_settled(code: str, limit: int = 3) -> list[dict]:
    """取某票最近已结算的决策（P1 决策记忆注入用）。任何失败返回空列表。"""
    sb = await _get_sb()
    if sb is None:
        return []
    try:
        res = (
            await sb.table(_TABLE)
            .select("*")
            .eq("code", code)
            .not_.is_("settled_at", "null")
            .order("data_date", desc=True)
            .limit(max(1, min(limit, 5)))
            .execute()
        )
        return res.data or []
    except Exception as e:
        print(f"[agent_decisions] 读记忆失败 {code}: {type(e).__name__}: {e}")
        return []


def memory_block(rows: list[dict]) -> str:
    """把已结算决策拼成可注入 LLM 上下文的记忆块。

    纪律：只注入「事实 + 偏差」，不下结论；没有结算样本时返回空串（零影响）。
    """
    if not rows:
        return ""
    parts: list[str] = []
    for r in rows:
        if r.get("settle_price") is None:
            continue
        entry = r.get("entry_price")
        if not entry:
            continue
        try:
            pnl = (float(r["settle_price"]) / float(entry) - 1) * 100
        except (TypeError, ZeroDivisionError):
            continue
        outcome = "方向一致" if r.get("hit") else "方向相反"
        parts.append(
            f"- {r.get('data_date', '')}：终审 {r.get('verdict', '?')}，动作 {r.get('action', '?')}，"
            f"入场 {entry}，{r.get('horizon_days', DEFAULT_HORIZON)} 个交易日后收盘 "
            f"{r['settle_price']}（{pnl:+.1f}%），{outcome}"
            + (f"。{r['reflection']}" if r.get("reflection") else "")
        )
    if not parts:
        return ""
    return (
        "\n\n系统决策记忆（该股票此前 agent 计划的实际结果，供参考、非依据；"
        "样本极少时统计意义有限，请以当前资料为主）：\n" + "\n".join(parts)
    )


async def settle_one(row: dict, settle_price: float) -> bool:
    """结算单行：按计划入场价基准算 pnl/hit，写回结算字段与反思。"""
    entry = row.get("entry_price")
    if not entry or entry <= 0:
        # 没有入场价（hold/reduce/avoid 或缺字段）的行不结算 pnl，只标记到期
        sb = await _get_sb()
        if sb is None:
            return False
        try:
            await sb.table(_TABLE).update(
                {"settled_at": _now_iso(), "settle_price": settle_price, "settle_basis": "close", "hit": None}
            ).eq("id", row["id"]).execute()
            return True
        except Exception as e:
            print(f"[agent_decisions] 结算失败 id={row.get('id')}: {e}")
            return False

    pnl_pct = (float(settle_price) / float(entry) - 1) * 100
    is_bull = row.get("action") in _BULL_ACTIONS
    hit = (pnl_pct > 0) if is_bull else (pnl_pct < 0)
    payload = {
        "settled_at": _now_iso(),
        "settle_price": round(float(settle_price), 4),
        "settle_basis": "close",
        "pnl_pct": round(pnl_pct, 2),
        "hit": hit,
        "reflection": reflection_from(row, float(settle_price), hit=hit),
    }
    sb = await _get_sb()
    if sb is None:
        return False
    try:
        await sb.table(_TABLE).update(payload).eq("id", row["id"]).execute()
        return True
    except Exception as e:
        print(f"[agent_decisions] 结算失败 id={row.get('id')}: {e}")
        return False


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


async def pending_settlements(before_date: str) -> list[dict]:
    """取 data_date <= before_date 且未结算的 adopted/ignored 行（cron 结算扫描）。"""
    sb = await _get_sb()
    if sb is None:
        return []
    try:
        res = (
            await sb.table(_TABLE)
            .select("*")
            .in_("status", ["adopted", "ignored"])
            .is_("settled_at", "null")
            .lte("data_date", before_date)
            .order("data_date", desc=False)
            .execute()
        )
        return res.data or []
    except Exception as e:
        print(f"[agent_decisions] 扫描待结算失败: {type(e).__name__}: {e}")
        return []


async def stats(user_id: str | None = None) -> dict | None:
    """agent 计划闭环统计（口径 agent_plan）：已结算数 / 命中数 / 命中率 / 平均 pnl。

    纪律：样本 < 5 时不给命中率（避免把 2/3=67% 这种噪声当读数）；
    未采纳对照组一并返回，供前端对比「采纳 vs 没采纳」。
    """
    sb = await _get_sb()
    if sb is None:
        return None
    try:
        q = sb.table(_TABLE).select("*").not_.is_("settled_at", "null").not_.is_("hit", "null")
        if user_id:
            q = q.eq("user_id", user_id)
        res = await q.execute()
        rows = res.data or []
        adopted = [r for r in rows if r.get("status") == "adopted"]
        ignored = [r for r in rows if r.get("status") == "ignored"]

        def _block(rs: list[dict]) -> dict:
            hits = [r for r in rs if r.get("hit")]
            pnls = [float(r["pnl_pct"]) for r in rs if r.get("pnl_pct") is not None]
            n = len(rs)
            return {
                "settled": n,
                "hits": len(hits),
                # 样本 <5 不给命中率：2/3=67% 这类读数只会骗自己
                "hit_rate": round(len(hits) / n * 100, 1) if n >= 5 else None,
                "avg_pnl_pct": round(sum(pnls) / len(pnls), 2) if pnls else None,
                "sample_note": None if n >= 5 else f"已结算样本仅 {n} 条，不足 5 条不给命中率（避免噪声读数）",
            }

        return {
            "adopted": _block(adopted),
            "ignored_control": _block(ignored),
            "caliber": calibers.describe("agent_plan"),
        }
    except Exception as e:
        print(f"[agent_decisions] 统计失败: {type(e).__name__}: {e}")
        return None

async def record_for_user_if_absent(
    *,
    code: str,
    name: str,
    data_date: str,
    plan: TradePlan,
    verdict: FundManagerVerdict | None,
    user_id: str,
) -> int | None:
    """同票同日同用户只落一行（防连点/重复分析重复落库）。"""
    sb = await _get_sb()
    if sb is None:
        return False
    try:
        dup = (
            await sb.table(_TABLE)
            .select("id")
            .eq("code", code)
            .eq("data_date", data_date)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        if dup.data:
            return None
        return await record_from_analysis(
            code=code, name=name, data_date=data_date, plan=plan, verdict=verdict, user_id=user_id
        )
    except Exception:
        return None
