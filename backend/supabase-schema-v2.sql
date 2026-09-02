-- AI 选股分析工具 · V2 迁移：预测准确率统计
-- 在 Supabase 控制台 → SQL Editor 中执行本文件

-- 大盘预测记录表
CREATE TABLE IF NOT EXISTS prediction_records (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    target_date DATE,                 -- 预测针对的交易日
    direction TEXT NOT NULL,          -- 预测方向：上涨/震荡/下跌（归一化）
    direction_raw TEXT,               -- 原始方向描述
    direction_score REAL,             -- 预测评分
    probability TEXT,
    expected_low REAL,
    expected_high REAL,
    summary TEXT,
    actual_change REAL,               -- 实际涨跌幅 %
    actual_direction TEXT,            -- 实际方向（结算后）
    hit BOOLEAN,                      -- 是否命中（结算后）
    settled_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_prediction_created ON prediction_records(created_at DESC);

-- 启用 RLS（仅登录用户可查自己的；未登录也可匿名保存）
ALTER TABLE prediction_records ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "predictions_public_read" ON prediction_records;
CREATE POLICY "predictions_public_read"
    ON prediction_records FOR SELECT
    USING (true);

DROP POLICY IF EXISTS "predictions_public_insert" ON prediction_records;
CREATE POLICY "predictions_public_insert"
    ON prediction_records FOR INSERT
    WITH CHECK (true);

DROP POLICY IF EXISTS "predictions_public_update" ON prediction_records;
CREATE POLICY "predictions_public_update"
    ON prediction_records FOR UPDATE
    USING (true);
