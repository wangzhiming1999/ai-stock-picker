-- AI 选股分析工具 · V19 迁移：跌停池每日落库
-- 在 Supabase 控制台 → SQL Editor 中执行本文件；或调用 POST /api/admin/migrate 自动执行。
-- 幂等，可重复执行。
--
-- 背景（limitdown_daily_snapshot）：与 v10 的 limitup_daily_snapshot 完全对称的问题 ——
-- 东财跌停板池 push2ex 只回溯约 15 个交易日（更早日期返回空池），因此
-- limitdown_service.repair_backtest 的样本窗口**永远只有 3 周且不会随时间变长**：
-- 今天跑是最近 15 天，明天跑还是最近 15 天，更早的样本永久丢失。
-- 本表把每日跌停池快照落下来，`repair_backtest` 的读路径优先用累积表补齐窗口外的日期 ——
-- 落库跑得越久，可回测窗口越长。
--
-- ⚠️ 本表**不改变**「跌停次日修复是负期望」这个结论，也不改变 `limitdown_repair`
-- 的 `unsupported` 分级（口径与证据登记见 tactic_evidence / calibers）。它只解决
-- **样本量**问题：现有结论建立在 133~190 个样本上，要把它验得更牢（或推翻）需要更长窗口。
--
-- ⚠️ 落库字段是 `normalize_limit_down` 输出的子集，**与涨停池字段不同名不同义**，照抄会错：
--   · `down_days`（连续跌停天数）对应涨停侧的 `boards`，跌停池没有 `lbc`；
--   · `last_seal_time`（最后封板时间）对应涨停侧的 `seal_time`，跌停池没有 `fbt` 首封时间；
--   · `seal_ratio` 语义**相反**：涨停侧封单厚＝买盘强，跌停侧封单厚＝**卖不掉**，不可跨侧比较。

-- ---------- 跌停池每日快照表 ----------

CREATE TABLE IF NOT EXISTS limitdown_daily_snapshot (
    id              BIGSERIAL PRIMARY KEY,
    trade_date      DATE NOT NULL,                 -- 跌停池归属交易日
    code            TEXT NOT NULL,
    name            TEXT DEFAULT '',
    price           NUMERIC DEFAULT 0,             -- 收盘价（= 跌停价）
    change_pct      NUMERIC DEFAULT 0,
    down_days       INTEGER NOT NULL DEFAULT 1,    -- 连续跌停天数（涨停侧是 lbc 连板数）
    last_seal_time  TEXT DEFAULT '',               -- 最后封板时间 HH:MM:SS（涨停侧没有该字段）
    seal_fund_yi    NUMERIC DEFAULT 0,             -- 封单金额（亿元）
    float_mv_yi     NUMERIC DEFAULT 0,             -- 流通市值（亿元）
    seal_ratio      NUMERIC DEFAULT 0,             -- 封单/流通 %（语义与涨停侧相反：卖不掉）
    turnover        NUMERIC DEFAULT 0,             -- 换手率 %
    amount_yi       NUMERIC DEFAULT 0,             -- 成交额（亿元）
    sector          TEXT DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (trade_date, code)                      -- 幂等写入的天然去重键
);

CREATE INDEX IF NOT EXISTS idx_limitdown_snap_date ON limitdown_daily_snapshot(trade_date);
CREATE INDEX IF NOT EXISTS idx_limitdown_snap_code ON limitdown_daily_snapshot(code, trade_date);

ALTER TABLE limitdown_daily_snapshot ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "limitdown_daily_snapshot_service" ON limitdown_daily_snapshot;
CREATE POLICY "limitdown_daily_snapshot_service" ON limitdown_daily_snapshot FOR ALL USING (true) WITH CHECK (true);
