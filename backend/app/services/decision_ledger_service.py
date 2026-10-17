"""决策留痕与复盘：把持仓决策落库，并回填「听建议 vs 没听」的收益差（A）。

## 它解决什么

V5.41 的 ``holding_decision_service`` 每天算出 sell / reduce / hold / skip 四态，
但**算完就丢** —— 没有地方记录「那天对这只票说了什么」，更没法回答
「听了建议的人后来赚了还是亏了」。后果：

* 用户无法验证这套判据有没有用，于是所有决策都像一次性意见；
* 我们也没有证据去**升级**（或推翻）这套判据 —— 没有收益口径，
  按项目证据闸门它只能停在 unsupported。

本模块补上留痕与回填两半：每日 cron 把决策写进 ``holding_decisions``；
用户实际卖出后，用 ``sim_trades`` 的成交价回填 ``follow_gain_pct``。

## 口径纪律（三条，都必须在 UI 上可见）

1. **听/没听是用户自选择，不是随机分组。** 愿意执行减仓建议的人可能本来就是
   更保守的投资者。因此收益差只是**描述性读数**，不是因果结论 ——
   写「听建议的平均收益高 X%」是错的，写「执行了减仓决策的持仓，其平均收益为 X%」
   才对。前者暗示工具带来收益，后者只陈述事实。
2. **复盘只用开/收盘价**（回测四铁律之一），不用盘中价。
3. **结论未过回测闸门前一律 unsupported**，不得宣称「本工具能提升收益」。

## 降级

表未建 / Supabase 未配置时**静默返回 0 或空**，不抛异常到调用方 ——
与 ``limitup_service.save_daily_snapshot`` 同一策略（v20 迁移可能还没跑）。
"""
from __future__ import annotations

import datetime as dt

from app.services import holding_decision_service, supabase_store

TABLE = "holding_decisions"

# 复盘窗口：只回填最近 N 天的未结算行。更早的决策对「现在该不该听」没有增量价值，
# 且全表扫会拖慢 cron。
_SETTLE_WINDOW_DAYS = 60

# 收益差展示的最小样本量：少于此数只报「样本不足」，不给平均值 ——
# 3 个样本的「平均 +8%」是噪声不是读数（项目既有纪律：先看 n）。
_MIN_SAMPLE = 5


def _configured() -> bool:
    return supabase_store is not None and supabase_store.is_configured()


async def save_daily_decisions(user_id: str, trade_date: dt.date | None = None) -> int:
    """把某用户当日的持仓决策写入留痕表（幂等，重复写覆盖）。

    返回写入行数；Supabase 未配置 / 表未建 / 无持仓时返回 0（静默降级）。
    """
    if not _configured():
        return 0
    date_key = (trade_date or dt.date.today()).isoformat()
    try:
        from app.services import portfolio_service

        advice = await portfolio_service.get_portfolio_advice(user_id)
        items = advice.get("holdings_advice") or []
        if not items:
            return 0

        from app.services import sector_flow_service

        try:
            sector_follow = await sector_flow_service.get_sector_follow()
        except Exception:  # noqa: BLE001 — 辅助读数不影响留痕
            sector_follow = None

        decisions = holding_decision_service.build_holding_decisions(items, sector_follow)
        by_code = {str(d["code"]): d for d in decisions}
        raw_by_code = {str(h.get("code")): h for h in items}

        rows = []
        for code, d in by_code.items():
            h = raw_by_code.get(code) or {}
            sig = h.get("signal") or {}
            rows.append(
                {
                    "user_id": user_id,
                    "trade_date": date_key,
                    "code": code,
                    "name": d.get("name") or "",
                    "action": d["decision"]["action"],
                    "reason": d["decision"].get("reason") or "",
                    "trigger_text": d["decision"].get("trigger") or "",
                    "invalidation": d["decision"].get("invalidation") or "",
                    "price": h.get("price") or 0,
                    "support": sig.get("support"),
                    "resistance": sig.get("resistance"),
                    "stop_loss": sig.get("stop_loss"),
                    "pnl_pct": d.get("pnl_pct"),
                    "position_pct": d.get("position_pct"),
                    "sector": d.get("sector") or "",
                    "sector_state": d.get("sector_state") or "",
                }
            )
        if not rows:
            return 0
        sb = await supabase_store.get_service_client()
        res = await (
            sb.table(TABLE)
            .upsert(rows, on_conflict="user_id,trade_date,code")
            .execute()
        )
        return len(res.data or [])
    except Exception as e:  # noqa: BLE001 — 表未建是预期内降级（需执行 v20 迁移）
        print(f"[decision-ledger] 留痕落库失败({date_key}): {e}")
        return 0


async def settle_pending() -> int:
    """回填已平仓的未结算决策行。

    对每个未结算行：若该 user 在 ``sim_trades`` 里有对应 code 的**卖出**记录，
    用卖出成交价回填 ``follow_gain_pct``（= 卖出价 vs 决策时点价）。

    返回回填行数；表未建 / 未配置时返回 0。
    """
    if not _configured():
        return 0
    try:
        sb = await supabase_store.get_service_client()
        since = (dt.date.today() - dt.timedelta(days=_SETTLE_WINDOW_DAYS)).isoformat()
        pend = await (
            sb.table(TABLE)
            .select("*")
            .eq("settled", False)
            .gte("trade_date", since)
            .execute()
        )
        rows = pend.data or []
        if not rows:
            return 0

        updated = 0
        for row in rows:
            code = row.get("code")
            if not code:
                continue
            # 该用户此 code 的卖出成交（取决策日之后最早一笔 —— 那是「听了建议后的离场」）
            trades = await (
                sb.table("sim_trades")
                .select("price,trade_date,side")
                .eq("user_id", row["user_id"])
                .eq("code", code)
                .eq("side", "sell")
                .gte("trade_date", row["trade_date"])
                .order("trade_date", desc=False)
                .limit(1)
                .execute()
            )
            t = (trades.data or [None])[0]
            if not t:
                continue
            base = row.get("price") or 0
            sell_price = t.get("price") or 0
            if not base or not sell_price:
                continue
            gain = round((sell_price / base - 1) * 100, 2)
            await (
                sb.table(TABLE)
                .update(
                    {
                        "settled": True,
                        "settle_price": sell_price,
                        "settle_date": t.get("trade_date"),
                        "follow_gain_pct": gain,
                    }
                )
                .eq("id", row["id"])
                .execute()
            )
            updated += 1
        return updated
    except Exception as e:  # noqa: BLE001
        print(f"[decision-ledger] 回填失败: {e}")
        return 0


async def get_review(user_id: str, days: int = 30) -> dict:
    """复盘读数：按动作分组的执行后收益 + 样本量。

    ⚠️ 返回的是**描述性读数**：听/没听是用户自选择，不是随机分组，
    因此不得解读为「本工具能带来 X% 超额」。UI 必须展示这句。
    """
    if not _configured():
        return _empty("决策留痕表未配置（需执行 v20 迁移）")
    try:
        sb = await supabase_store.get_service_client()
        since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
        res = await (
            sb.table(TABLE)
            .select("*")
            .eq("user_id", user_id)
            .gte("trade_date", since)
            .execute()
        )
        rows = res.data or []
    except Exception as e:  # noqa: BLE001
        return _empty(f"读取失败：{e}")

    if not rows:
        return _empty("窗口内没有持仓决策记录")

    by_action: dict[str, list[dict]] = {}
    for r in rows:
        by_action.setdefault(str(r.get("action") or "unknown"), []).append(r)

    groups = []
    for action in ("sell", "reduce", "hold", "skip"):
        items = by_action.get(action) or []
        if not items:
            continue
        settled = [i for i in items if i.get("follow_gain_pct") is not None]
        gains = [float(i["follow_gain_pct"]) for i in settled]
        groups.append(
            {
                "action": action,
                "label": _label(action),
                "decided": len(items),
                "settled": len(settled),
                # 样本不足时不给平均值 —— 3 个样本的「平均 +8%」是噪声不是读数
                "avg_gain_pct": round(sum(gains) / len(gains), 2) if len(gains) >= _MIN_SAMPLE else None,
                "median_gain_pct": (
                    round(sorted(gains)[len(gains) // 2], 2) if len(gains) >= _MIN_SAMPLE else None
                ),
                "sample_sufficient": len(gains) >= _MIN_SAMPLE,
            }
        )

    total_settled = sum(g["settled"] for g in groups)
    return {
        "available": True,
        "note": None,
        "window_days": days,
        "total_decided": len(rows),
        "total_settled": total_settled,
        "groups": groups,
        # 口径免责：自选择偏差 + 未过闸门，两句都必须随数据下发
        "caveats": [
            "听/没听建议是用户自选择，不是随机分组 —— 愿意执行减仓的人可能本来就偏保守，"
            "收益差只是描述性读数，不能解读为「本工具带来超额」。",
            "复盘用收盘/成交价，未含盘中路径；结论未过回测闸门前不作为策略依据。",
        ],
    }


def _label(action: str) -> str:
    from app.services import decision

    return decision.DECISION_LABEL.get(action, action)


def _empty(note: str) -> dict:
    return {
        "available": False,
        "note": note,
        "window_days": 0,
        "total_decided": 0,
        "total_settled": 0,
        "groups": [],
        "caveats": [
            "听/没听建议是用户自选择，不是随机分组，收益差只是描述性读数。",
            "复盘用收盘/成交价，未过回测闸门前不作为策略依据。",
        ],
    }
