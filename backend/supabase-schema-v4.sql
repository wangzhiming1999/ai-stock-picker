-- AI 选股分析工具 · V4 迁移：价格预警中心
-- 在 Supabase 控制台 → SQL Editor 中执行本文件

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
