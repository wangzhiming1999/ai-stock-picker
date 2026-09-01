-- AI 选股分析工具 · Supabase 数据库结构
-- 在 Supabase 控制台 → SQL Editor 中执行本文件

-- 分析批次表（关联用户）
CREATE TABLE IF NOT EXISTS analysis_batches (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    codes TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'mock',
    total INTEGER NOT NULL DEFAULT 0,
    avg_score REAL
);

-- 分析结果表
CREATE TABLE IF NOT EXISTS analysis_results (
    id BIGSERIAL PRIMARY KEY,
    batch_id BIGINT NOT NULL REFERENCES analysis_batches(id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    overall_score REAL NOT NULL,
    summary TEXT,
    dimensions JSONB NOT NULL DEFAULT '[]',
    risks JSONB NOT NULL DEFAULT '[]',
    suggestions JSONB NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_results_batch ON analysis_results(batch_id);
CREATE INDEX IF NOT EXISTS idx_batches_user_created ON analysis_batches(user_id, created_at DESC);

-- 启用 RLS（行级安全）
ALTER TABLE analysis_batches ENABLE ROW LEVEL SECURITY;
ALTER TABLE analysis_results ENABLE ROW LEVEL SECURITY;

-- 用户只能看到自己的批次
DROP POLICY IF EXISTS "users_see_own_batches" ON analysis_batches;
CREATE POLICY "users_see_own_batches"
    ON analysis_batches FOR SELECT
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "users_insert_own_batches" ON analysis_batches;
CREATE POLICY "users_insert_own_batches"
    ON analysis_batches FOR INSERT
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "users_update_own_batches" ON analysis_batches;
CREATE POLICY "users_update_own_batches"
    ON analysis_batches FOR UPDATE
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "users_see_own_results" ON analysis_results;
CREATE POLICY "users_see_own_results"
    ON analysis_results FOR SELECT
    USING (EXISTS (SELECT 1 FROM analysis_batches b WHERE b.id = batch_id AND b.user_id = auth.uid()));

DROP POLICY IF EXISTS "users_insert_own_results" ON analysis_results;
CREATE POLICY "users_insert_own_results"
    ON analysis_results FOR INSERT
    WITH CHECK (EXISTS (SELECT 1 FROM analysis_batches b WHERE b.id = batch_id AND b.user_id = auth.uid()));

DROP POLICY IF EXISTS "users_update_own_results" ON analysis_results;
CREATE POLICY "users_update_own_results"
    ON analysis_results FOR UPDATE
    USING (EXISTS (SELECT 1 FROM analysis_batches b WHERE b.id = batch_id AND b.user_id = auth.uid()));
