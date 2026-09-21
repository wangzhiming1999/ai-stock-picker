-- AI 选股分析工具 · V12 迁移：决策先锋三维榜快照表
-- 在 Supabase 控制台 → SQL Editor 中执行本文件；或调用 POST /api/admin/migrate 自动执行。
-- 幂等，可重复执行。
--
-- 背景：「决策先锋」按 暗盘资金 / 趋势 / 活跃度 三维打分选股（vanguard_service）。
-- 与四维榜（quad_snapshots）是**两条独立的榜单**：维度不同、候选池不同、口径不可比。
-- 因此单独建表，不复用 quad_snapshots —— 复用会让「这份榜是哪个口径跑出来的」变成猜测。
--
-- 整份结果按最近交易日缓存一份，因此资金流批次（东财 clist 批量端点）每个交易日
-- 只需拉 1~2 次，而不是每次页面加载都拉。这就是本表存在的理由。
--
-- ⚠️ 表未建时 vanguard_service 会静默降级为「仅进程内缓存」：不报错、功能仍在，
--    只是冷实例会重复拉一次资金流批次。不会因为漏跑迁移而白屏。
-- ⚠️ 线上若已存在同名表：`CREATE TABLE IF NOT EXISTS` 会**静默跳过**整段，
--    既不报错也不对齐。执行后请用 information_schema.columns 核一次实际列。

CREATE TABLE IF NOT EXISTS vanguard_snapshots (
    id            BIGSERIAL PRIMARY KEY,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    snapshot_date DATE NOT NULL,                        -- 归属交易日（按最近交易日取，不是自然日）
    result        JSONB NOT NULL DEFAULT '{}'::jsonb,   -- 整份三维榜结果（含板块/抱团/龙头与资金快照映射）
    UNIQUE (snapshot_date)                              -- 每交易日一份
);

CREATE INDEX IF NOT EXISTS idx_vanguard_snapshots_date ON vanguard_snapshots(snapshot_date);

ALTER TABLE vanguard_snapshots ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "vanguard_snapshots_service" ON vanguard_snapshots;
CREATE POLICY "vanguard_snapshots_service" ON vanguard_snapshots
    FOR ALL USING (true) WITH CHECK (true);
