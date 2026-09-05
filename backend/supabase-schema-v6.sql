-- AI 选股分析工具 · V6 迁移：全市场快照缓存（性能/成本优化）
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
