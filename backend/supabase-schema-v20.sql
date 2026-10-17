-- AI 选股分析工具 · V20 迁移：持仓决策留痕与复盘
-- 在 Supabase 控制台 → SQL Editor 中执行本文件；或调用 POST /api/admin/migrate 自动执行。
-- 幂等，可重复执行。
--
-- 背景（holding_decisions）：V5.41 上线了结构化持仓决策层（holding_decision_service），
-- 给出 sell / reduce / hold / skip 四态 + 结构位触发价。但那些决策**算完就丢** ——
-- 没有任何地方记录「那天对这只票说了什么」，更没法回答「听了建议的人后来赚了还是亏了」。
-- 后果是所有决策都像一次性意见，而不是可复盘的策略：用户无法验证它有没有用，
-- 我们也没有证据去升级（或推翻）这套判据。
--
-- 本表把每日持仓决策落下来，配合 sim_trades 回填「决策时点价 vs 实际成交价」，
-- 算出**听建议与没听建议的收益差**。这是让决策链路可信的唯一办法。
--
-- ⚠️ 口径纪律（与 tactic_evidence / calibers 一致）：
--   · 本表记录的是**决策**，不是**信号**；复盘结论未通过回测闸门前一律标 unsupported，
--     不得据此宣称「本工具能提升收益」；
--   · 听/没听是用户自选择（self-selection），不是随机分组 —— 愿意执行减仓建议的人
--     可能本来就是更保守的投资者。因此收益差只能作为**描述性读数**，
--     不能当因果结论。这一点必须写在 UI 上。
--   · 复盘只用开/收盘价（回测四铁律之一），不用盘中价。

-- ---------- 持仓决策每日留痕表 ----------

CREATE TABLE IF NOT EXISTS holding_decisions (
    id              BIGSERIAL PRIMARY KEY,
    user_id         TEXT NOT NULL,
    trade_date      DATE NOT NULL DEFAULT CURRENT_DATE,   -- 决策归属交易日
    code            TEXT NOT NULL,
    name            TEXT DEFAULT '',
    -- 决策本体（与 services/decision.py 的 decision.make() 对应）
    action          TEXT NOT NULL,                          -- sell / reduce / hold / skip
    reason          TEXT DEFAULT '',
    trigger_text    TEXT DEFAULT '',                        -- 触发条件（人类可读）
    invalidation    TEXT DEFAULT '',                        -- 失效条件
    -- 决策锚定的结构位（复盘的基准价，不用现价系数）
    price           NUMERIC DEFAULT 0,                      -- 决策时点价
    support         NUMERIC,                                -- 主支撑
    resistance      NUMERIC,                                -- 主压力
    stop_loss       NUMERIC,                                -- 止损位
    -- 上下文（用于复盘时分维度看，不做加权）
    pnl_pct         NUMERIC,                                -- 决策时点浮盈亏
    position_pct    NUMERIC,                                -- 决策时点仓位占比
    sector          TEXT DEFAULT '',
    sector_state    TEXT DEFAULT '',                        -- 板块资金四态
    -- 复盘回填（用户实际卖出后由 settle 写入）
    settled         BOOLEAN NOT NULL DEFAULT FALSE,         -- 是否已回填
    settle_price    NUMERIC,                                -- 用户实际成交价
    settle_date     DATE,                                   -- 实际成交日
    follow_gain_pct NUMERIC,                                -- 听建议的收益（卖出价 vs 决策时点价）
    ignore_gain_pct NUMERIC,                                -- 同期未听的收益（用于对照，可为空）
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, trade_date, code)                      -- 幂等写入的天然去重键
);

CREATE INDEX IF NOT EXISTS idx_holding_decisions_user ON holding_decisions(user_id, trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_holding_decisions_action ON holding_decisions(user_id, trade_date, action);
-- 复盘回填要按「未结算 + 已平仓」扫，单列索引避免全表过滤
CREATE INDEX IF NOT EXISTS idx_holding_decisions_unsettled ON holding_decisions(settled, trade_date);

ALTER TABLE holding_decisions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "holding_decisions_service" ON holding_decisions;
CREATE POLICY "holding_decisions_service" ON holding_decisions FOR ALL USING (true) WITH CHECK (true);
