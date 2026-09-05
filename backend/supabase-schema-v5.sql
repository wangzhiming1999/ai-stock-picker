-- AI 选股分析工具 · V5 迁移：模拟盘（Paper Trading）
-- 在 Supabase 控制台 → SQL Editor 中执行本文件
--
-- 设计要点（详见 docs/sim-trading-plan.md）：
--   1. cash 直接落在 user_profiles，不新建账户表；
--   2. sim_trades 是模拟盘唯一数据源，持仓在查询时聚合（平均成本法，避免双写不一致）；
--   3. portfolio_snapshots 由每日收盘 cron 写入，用于净值曲线；
--   4. 历史行 cash 默认 0，初始化时由后端补成 total_capital（见 sim_service.init_account）。

-- 1) 用户表增加可扣减现金列
ALTER TABLE user_profiles
  ADD COLUMN IF NOT EXISTS cash NUMERIC NOT NULL DEFAULT 0;

-- 2) 模拟盘成交流水（核心新表）
CREATE TABLE IF NOT EXISTS sim_trades (
    id            BIGSERIAL PRIMARY KEY,
    user_id       TEXT NOT NULL,
    code          TEXT NOT NULL,
    name          TEXT DEFAULT '',
    side          TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    price         NUMERIC NOT NULL,
    shares        INTEGER NOT NULL,
    fee           NUMERIC NOT NULL DEFAULT 0,
    amount        NUMERIC NOT NULL,            -- 买: price*shares+fee；卖: price*shares-fee
    executed_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    trade_date    DATE NOT NULL DEFAULT CURRENT_DATE,  -- T+1 判定用
    source        TEXT NOT NULL DEFAULT 'manual'
                  CHECK (source IN ('manual', 'briefing', 'recommend')),
    related_reco_id TEXT,                      -- 关联推荐/预测 id，闭环用（可空）
    note          TEXT DEFAULT '',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sim_trades_user ON sim_trades(user_id, executed_at DESC);
CREATE INDEX IF NOT EXISTS idx_sim_trades_code ON sim_trades(user_id, code);

-- 3) 组合净值快照（收益曲线）
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id            BIGSERIAL PRIMARY KEY,
    user_id       TEXT NOT NULL,
    snapshot_date DATE NOT NULL DEFAULT CURRENT_DATE,
    cash          NUMERIC NOT NULL DEFAULT 0,
    market_value  NUMERIC NOT NULL DEFAULT 0,
    total_value   NUMERIC NOT NULL DEFAULT 0,
    total_pnl     NUMERIC NOT NULL DEFAULT 0,
    total_pnl_pct NUMERIC NOT NULL DEFAULT 0,
    positions_cnt INTEGER NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_portfolio_snapshots_user ON portfolio_snapshots(user_id, snapshot_date DESC);

-- RLS：service client 全权（与 user_holdings / alert 表一致，后端按 user_id 过滤隔离）
ALTER TABLE sim_trades ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "sim_trades_service" ON sim_trades;
CREATE POLICY "sim_trades_service" ON sim_trades FOR ALL USING (true) WITH CHECK (true);

ALTER TABLE portfolio_snapshots ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "portfolio_snapshots_service" ON portfolio_snapshots;
CREATE POLICY "portfolio_snapshots_service" ON portfolio_snapshots FOR ALL USING (true) WITH CHECK (true);
