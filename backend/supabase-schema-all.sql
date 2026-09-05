-- AI 选股分析工具 · 全量合并迁移（v4 + v5 + v6）
-- 在 Supabase 控制台 → SQL Editor 中执行本文件
--
-- ⚠️ 本文件内容等价于按顺序执行 supabase-schema-v4.sql + v5.sql + v6.sql，
--    三份拆分版本各自独立维护，新环境建议改用「按序执行拆分版本」或
--    POST /api/admin/migrate 自动迁移，避免此合并副本与拆分版本不同步。
--    本文件保留仅为一次性全量执行提供便利，所有语句均幂等，可重复执行。

-- 预警规则表：用户对某只股票设定的价格触发条件
CREATE TABLE IF NOT EXISTS alert_rules (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    code TEXT NOT NULL,                       -- 6 位股票代码
    name TEXT DEFAULT '',                     -- 股票名称（冗余，便于展示）
    type TEXT NOT NULL,                       -- stop_loss(<=触发) / price_target(>=触发) / breakdown(<=破位)
    threshold REAL NOT NULL,                  -- 触发阈值（绝对价格）
    enabled BOOLEAN DEFAULT TRUE,
    note TEXT DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alert_rules_user ON alert_rules(user_id, enabled);
CREATE INDEX IF NOT EXISTS idx_alert_rules_code ON alert_rules(code);

-- 预警事件表：规则命中后落库的记录（用户可查看/标记已读）
CREATE TABLE IF NOT EXISTS alert_events (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    rule_id BIGINT,                           -- 关联规则（盯盘类可为空）
    code TEXT NOT NULL,
    name TEXT DEFAULT '',
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    price REAL,
    severity TEXT DEFAULT 'warn',            -- info / warn / danger
    is_read BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alert_events_user ON alert_events(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_alert_events_unread ON alert_events(user_id, is_read, created_at DESC);

-- RLS：service client 全权（与 user_holdings 一致，后端按 user_id 过滤隔离）
ALTER TABLE alert_rules ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "alert_rules_service" ON alert_rules;
CREATE POLICY "alert_rules_service" ON alert_rules FOR ALL USING (true) WITH CHECK (true);

ALTER TABLE alert_events ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "alert_events_service" ON alert_events;
CREATE POLICY "alert_events_service" ON alert_events FOR ALL USING (true) WITH CHECK (true);
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

-- AI 选股分析工具 · 全市场快照缓存（性能/成本优化）
-- 在 Supabase 控制台 → SQL Editor 中执行本文件
--
-- 背景：akshare stock_zh_a_spot 在 Vercel serverless 上单次拉取全市场约需 ~70s，
-- 远超常规请求预算。把快照落库（单行 upsert），请求路径优先读库（<0.5s），
-- 跨实例/跨请求复用，每日最多拉几次。表未建时后端静默降级为直连 akshare。

CREATE TABLE IF NOT EXISTS market_spot_cache (
    id          BIGINT PRIMARY KEY DEFAULT 1,           -- 单行：始终只有一条最新快照
    rows        JSONB NOT NULL,                         -- 全市场快照数组（code/name/price/change/amount）
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE market_spot_cache ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "market_spot_cache_service" ON market_spot_cache;
CREATE POLICY "market_spot_cache_service" ON market_spot_cache FOR ALL USING (true) WITH CHECK (true);

