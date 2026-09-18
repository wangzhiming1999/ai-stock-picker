-- AI 选股分析工具 · V9 迁移：Agent 决策记录表（TradingAgents 执行闭环）
-- 在 Supabase 控制台 → SQL Editor 中执行本文件；或调用 POST /api/admin/migrate 自动执行。
-- 幂等，可重复执行。
--
-- 背景：深度分析的四层链路（分析师 → 多空辩论 → 交易员计划 → 风控终审）此前是
-- 「跑完即散」的一次性展示，没有任何表记录「agent 说买 → 实际结果如何」。
-- 本表是 agent 的 track record：终审通过的计划一键转入模拟盘时落一行，
-- 到期由每日 cron 按计划价与实际行情结算，从而：
--   1. agent 计划拥有可验证的胜率/盈亏（口径 agent_plan，登记在 calibers.py）；
--   2. 同票重分析时把「上次计划 + 实际偏差 + 反思」注入 LLM 上下文（决策记忆）；
--   3. 与「未采纳/被否决」计划形成对照组（status='ignored'/'rejected' 行也落库）。
--
-- **表未建时后端全部静默降级**（from-plan 按钮报错提示、记忆注入跳过、结算跳过），
-- 不影响任何现有链路 —— 与 market_spot_cache / market_source_state 同一套可选迁移策略。

CREATE TABLE IF NOT EXISTS agent_decisions (
    id             BIGSERIAL PRIMARY KEY,
    user_id        TEXT,                          -- NULL = 平台记录（对照样本，无归属用户）
    code           TEXT NOT NULL,
    name           TEXT DEFAULT '',
    data_date      DATE NOT NULL,                 -- 计划产出日（交易日）
    -- 计划快照（from TradePlan + FundManagerVerdict）
    action         TEXT NOT NULL,                 -- buy | add | hold | reduce | avoid
    verdict        TEXT NOT NULL,                 -- approved | demoted | rejected（终审结论）
    entry_price    NUMERIC,
    stop_price     NUMERIC,
    target_price   NUMERIC,
    position_pct   NUMERIC DEFAULT 0,             -- 终审后仓位 %（rejected 为 0）
    horizon_days   INTEGER NOT NULL DEFAULT 5,    -- 结算窗口：N 个交易日后按收盘价结算
    -- 执行状态：adopted=已转入模拟盘；ignored=用户没采纳；rejected=终审否决（自动落对照行）
    status         TEXT NOT NULL DEFAULT 'ignored'
                   CHECK (status IN ('adopted', 'ignored', 'rejected')),
    -- 执行回填
    sim_trade_id   BIGINT,                        -- adopted 时关联 sim_trades.id
    -- 结算回填（cron 到期回写；停牌等拿不到行情时顺延，不乱填基准）
    settled_at     TIMESTAMPTZ,
    settle_price   NUMERIC,                       -- 到期日收盘价
    settle_basis   TEXT,                          -- close=到期收盘 | none=尚未结算
    pnl_pct        NUMERIC,                       -- (settle/entry - 1)*100，以计划入场价为基准
    hit            BOOLEAN,                       -- 方向一致（buy 类：settle > entry）
    reflection     TEXT DEFAULT '',               -- P1 决策记忆：到期反思（代码模板生成）
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_decisions_user ON agent_decisions(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_decisions_code ON agent_decisions(code, data_date DESC);

-- 结算扫描专用部分索引：只扫「待结算」行，量级恒小
CREATE INDEX IF NOT EXISTS idx_agent_decisions_pending ON agent_decisions(data_date)
    WHERE status IN ('adopted', 'ignored') AND settled_at IS NULL;

ALTER TABLE agent_decisions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "agent_decisions_service" ON agent_decisions;
CREATE POLICY "agent_decisions_service" ON agent_decisions FOR ALL USING (true) WITH CHECK (true);
