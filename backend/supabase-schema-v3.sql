-- AI 选股分析工具 · V3 迁移：每日推荐跟踪 + 胜率统计
-- 在 Supabase 控制台 → SQL Editor 中执行本文件

-- 每日推荐记录表（跟踪推荐后实际表现，用于胜率统计）
CREATE TABLE IF NOT EXISTS daily_recommendations (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    rec_date DATE NOT NULL,             -- 推荐日期
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    recommend_price REAL,               -- 推荐时价格
    reason TEXT,
    confidence REAL,
    source TEXT DEFAULT 'llm',
    -- 结算字段（次一交易日表现）
    next_close REAL,                    -- 推荐后首个交易日收盘价
    next_return REAL,                   -- 次日收益率 %
    settled_at TIMESTAMPTZ,
    hit BOOLEAN                         -- 次日上涨为 true
);

CREATE INDEX IF NOT EXISTS idx_daily_rec_date ON daily_recommendations(rec_date, code);

-- 胜率统计汇总表（可缓存，避免每次统计扫全表）
CREATE TABLE IF NOT EXISTS winrate_snapshot (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    snapshot_date DATE NOT NULL,
    prediction_total INTEGER,
    prediction_hit INTEGER,
    prediction_rate REAL,
    recommend_total INTEGER,
    recommend_hit INTEGER,
    recommend_rate REAL
);

-- RLS：公开只读 + 服务端写
ALTER TABLE daily_recommendations ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "daily_rec_public_read" ON daily_recommendations;
CREATE POLICY "daily_rec_public_read" ON daily_recommendations FOR SELECT USING (true);
DROP POLICY IF EXISTS "daily_rec_service_insert" ON daily_recommendations;
CREATE POLICY "daily_rec_service_insert" ON daily_recommendations FOR INSERT WITH CHECK (true);
DROP POLICY IF EXISTS "daily_rec_service_update" ON daily_recommendations;
CREATE POLICY "daily_rec_service_update" ON daily_recommendations FOR UPDATE USING (true);

ALTER TABLE winrate_snapshot ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "winrate_public_read" ON winrate_snapshot;
CREATE POLICY "winrate_public_read" ON winrate_snapshot FOR SELECT USING (true);
DROP POLICY IF EXISTS "winrate_service_insert" ON winrate_snapshot;
CREATE POLICY "winrate_service_insert" ON winrate_snapshot FOR INSERT WITH CHECK (true);
