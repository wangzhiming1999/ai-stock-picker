"""定时任务路由：Vercel Cron 触发每日收盘结算。"""
import datetime as dt
import os

from fastapi import APIRouter, HTTPException, Request

from app.services import alert_service, quad_service, recommend_service, sim_service, winrate_service

router = APIRouter(prefix="/api/cron", tags=["cron"])
_CN_TZ = dt.timezone(dt.timedelta(hours=8))


def _authorize(request: Request) -> None:
    """校验 CRON_SECRET，未配置或失败抛异常。

    兼容两种鉴权：
    - Vercel Cron 平台自动携带 `Authorization: Bearer <CRON_SECRET>`
    - 手动运维触发：`X-Admin-Token: <ADMIN_TOKEN>`（与 /api/admin/migrate 共用凭据）

    背景：2026-09-05 发现 Vercel Cron 调用连续 401（secret 不匹配）导致胜率闭环
    从未结算过；双通道鉴权保证平台 secret 出错时仍可手动触发兜底。
    """
    admin_token = os.getenv("ADMIN_TOKEN", "")
    if admin_token and request.headers.get("x-admin-token", "") == admin_token:
        return

    expected = os.getenv("CRON_SECRET", "")
    if not expected:
        raise HTTPException(status_code=503, detail="CRON_SECRET 未配置")
    auth = request.headers.get("authorization", "")
    provided = auth.removeprefix("Bearer ").strip() if auth.startswith("Bearer ") else ""
    if provided != expected:
        raise HTTPException(status_code=401, detail="未授权")


@router.api_route("/daily", methods=["GET", "POST"])
async def daily_cron(request: Request):
    """每日收盘定时任务：结算预测 + 结算推荐 + 刷新胜率快照 + 预警兜底评估。

    Vercel Cron 触发，校验 Authorization Bearer 与 CRON_SECRET 一致。
    V6 预警兜底评估合并进每日任务（Hobby 计划 cron 数量受限，高频实时性由前端盯盘轮询保证）。
    """
    _authorize(request)
    try:
        result = await winrate_service.run_daily_cron()
        # V6 预警兜底：合并进每日结算，避免超出 Vercel Hobby cron 数量限制
        try:
            result["alert_events"] = await alert_service.evaluate_all()
        except Exception as ae:  # 预警评估失败不影响胜率结算结果
            print(f"[cron] alert evaluate_all failed: {ae}")
            result["alert_events"] = None
        # V5 模拟盘：为所有有模拟流水的用户写当日净值快照（表未建时静默失败）
        try:
            result["sim_snapshots"] = await sim_service.snapshot_all_users()
        except Exception as se:
            print(f"[cron] sim snapshot failed: {se}")
            result["sim_snapshots"] = None
        # Agent 执行闭环：到期结算 agent 决策（agent_decisions 表未建时静默跳过）
        try:
            result["agent_settled"] = await sim_service.settle_agent_decisions()
        except Exception as ge:
            print(f"[cron] agent decisions settle failed: {ge}")
            result["agent_settled"] = None
        # 每日收盘推荐：规则选股 + AI 解释（落库 + 预热全市场快照缓存，用户白天访问秒回）
        try:
            result["recommendations"] = await recommend_service.generate_daily_recommendations(force_refresh=True)
        except Exception as re_:
            print(f"[cron] recommend gen failed: {re_}")
            result["recommendations"] = None
        # 涨停池每日落库：收盘后把当日涨停池写入累积表（回测窗口自积累）。
        # 表未建/Supabase 未配置时内部静默返回 0，不影响其他结算步骤。
        try:
            from app.services import limitup_service

            result["limitup_snapshot_rows"] = await limitup_service.save_daily_snapshot()
            # 保留窗口清理：只写不删会撞 Supabase 免费额度，而写路径失败是静默的
            # （save_daily_snapshot 捕获异常后返回 0）—— 清理是让它不静默爆掉的前提。
            result["limitup_snapshot_purged"] = await limitup_service.purge_old_snapshots()
        except Exception as le:
            print(f"[cron] limitup snapshot save failed: {le}")
            result["limitup_snapshot_rows"] = None
        # 跌停池每日落库：与涨停池同一理由 —— 跌停板池接口同样只回溯约 15 个交易日，
        # repair_backtest 的样本窗口不会随时间变长。表未建/Supabase 未配置时静默返回 0。
        try:
            from app.services import limitdown_service

            result["limitdown_snapshot_rows"] = await limitdown_service.save_daily_snapshot()
            result["limitdown_snapshot_purged"] = await limitdown_service.purge_old_snapshots()
        except Exception as de:
            print(f"[cron] limitdown snapshot save failed: {de}")
            result["limitdown_snapshot_rows"] = None
        # 抢封板收益闭环：当日封板判定 + 历史待结算行的 D+1 开盘结算。
        # 此前这两步只在 GET /api/seize/history（用户打开抢板历史页）里触发 ——
        # 实测 20 天 56 条落库 / 0 条结算 / next_open 恒空，样本从没进过账。
        # 内部任何一步失败都进 errors 返回，不吞。
        try:
            from app.services import seize_service

            result["seize_settle"] = await seize_service.settle_daily()
        except Exception as ze:
            print(f"[cron] seize settle failed: {ze}")
            result["seize_settle"] = None
        # 决策留痕与复盘（V5.42）：① 为所有有持仓的用户写当日持仓决策
        # ② 回填已平仓的未结算决策行（听建议的收益）。
        # 表未建时内部静默返回 0（需执行 v20 迁移），不影响其他结算步骤。
        try:
            from app.services import decision_ledger_service, portfolio_service

            ledger_rows = 0
            ledger_settled = 0
            user_ids = await portfolio_service.list_user_ids_with_holdings()
            for uid in user_ids:
                ledger_rows += await decision_ledger_service.save_daily_decisions(uid)
            ledger_settled = await decision_ledger_service.settle_pending()
            result["decision_ledger_rows"] = ledger_rows
            result["decision_ledger_settled"] = ledger_settled
            # 决策 → 告警规则同步（V5.42 B）：把持仓决策的结构位同步成自动规则，
            # 用户不必自己把同一个价位录第二遍。手动规则永不被覆盖（note 区分）。
            try:
                from app.services import alert_service, holding_decision_service, sector_flow_service

                synced = 0
                sector_follow = None
                try:
                    sector_follow = await sector_flow_service.get_sector_follow()
                except Exception:  # noqa: BLE001
                    sector_follow = None
                for uid in user_ids:
                    advice = await portfolio_service.get_portfolio_advice(uid)
                    items = advice.get("holdings_advice") or []
                    for d in holding_decision_service.build_holding_decisions(items, sector_follow):
                        r = await alert_service.sync_decision_rules(uid, d)
                        if r.get("action") in ("created", "updated"):
                            synced += 1
                result["decision_alert_rules"] = synced
            except Exception as se:
                print(f"[cron] decision alert sync failed: {se}")
                result["decision_alert_rules"] = None
        except Exception as dle:
            print(f"[cron] decision ledger failed: {dle}")
            result["decision_ledger_rows"] = None
        if not result.get("ok", True):
            raise HTTPException(
                status_code=502,
                detail={"message": "核心结算部分失败，其余每日任务已继续执行", "result": result},
            )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"定时任务失败: {e}")


@router.api_route("/quad", methods=["GET", "POST"])
async def quad_cron(request: Request):
    """收盘后预生成当日四维牛股榜，让用户白天访问秒回。

    在每日收盘（北京 16:05）由 Vercel Cron 触发。
    """
    _authorize(request)
    try:
        result = await quad_service.generate_quad_rankings(force_refresh=True)
        return {"ok": True, "date": result["date"], "items": len(result["items"]), "pool": result["pool_size"]}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"四维牛股榜预热失败: {e}")


@router.post("/monitor")
async def monitor_cron(request: Request):
    """服务端盘中监控入口，供外部调度器每分钟调用；浏览器关闭后仍可落库预警。"""
    _authorize(request)
    now = dt.datetime.now(dt.timezone.utc).astimezone(_CN_TZ)
    local_time = now.time()
    market_open = now.weekday() < 5 and (
        dt.time(9, 15) <= local_time <= dt.time(11, 30)
        or dt.time(13, 0) <= local_time <= dt.time(15, 0)
    )
    if not market_open:
        return {"ok": True, "skipped": "market_closed", "executed_at": now.isoformat(timespec="seconds")}
    try:
        # 连板接力自动建仓：只在开盘初期（9:15~9:45）执行一次判定 ——
        # 判定数据是 T-1 日涨停池 + 今日开盘价，9:25 集合竞价后开盘价才确定；
        # 9:45 之后开盘结构已经走样（追高成交价失真），不再按「开盘价」口径建仓。
        relay_result = None
        if dt.time(9, 15) <= local_time <= dt.time(9, 45):
            try:
                relay_result = await sim_service.auto_relay_buy_all()
            except Exception as re_:
                print(f"[cron] relay auto buy failed: {re_}")
                relay_result = {"errors": [f"fatal:{re_}"]}
        result = await alert_service.evaluate_all()
        # 抢封板信号落库：此前只在封板雷达被前端轮询时触发 → 没人打开「抢板」页的交易日
        # 一条样本都没有（实测 20 天只有 3 天有数据）。复用 get_radar 的 15s 缓存与
        # 120s 落库节流，不为调度新增额外行情请求。
        try:
            from app.services import seize_service

            result["seize_ingest"] = await seize_service.ingest_intraday()
        except Exception as ze:
            print(f"[cron] seize ingest failed: {ze}")
            result["seize_ingest"] = None
        return {
            "ok": True,
            "executed_at": now.isoformat(timespec="seconds"),
            "relay_auto_buy": relay_result,
            **result,
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"盘中监控失败: {type(e).__name__}")
