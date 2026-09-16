-- AI 选股分析工具 · V8 迁移：行情源失败标记（跨实例冷却共享）
-- 在 Supabase 控制台 → SQL Editor 中执行本文件；或调用 POST /api/admin/migrate 自动执行。
-- 幂等，可重复执行。
--
-- 背景：Serverless 多实例内存不互通，而原实现把「最近一次行情源失败」只放在进程内存里。
-- 后果是 A 实例已被东财风控、B 实例仍去撞行情源 —— 每个请求都要空等数十秒才返回 502，
-- 同时持续刷新风控窗口，把本可 3 分钟自愈的封禁拖长；前端也因此拿不到正确的剩余秒数。
--
-- 本表只有一行，记录最近一次失败时刻，让冷却窗口对所有实例生效。
-- **表未建时后端会静默降级为纯进程内冷却**（不报错、不影响请求），因此本迁移可选：
-- 不执行也能跑，只是多实例并发时保护变弱。

CREATE TABLE IF NOT EXISTS market_source_state (
    id          BIGINT PRIMARY KEY DEFAULT 1,   -- 单行：始终只有一条最新状态
    failed_at   TIMESTAMPTZ,                    -- 最近一次行情源失败时刻；无行或 NULL = 正常
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE market_source_state ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "market_source_state_service" ON market_source_state;
CREATE POLICY "market_source_state_service" ON market_source_state FOR ALL USING (true) WITH CHECK (true);
