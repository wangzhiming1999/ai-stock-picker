-- AI 选股分析工具 · V10 迁移：涨停池每日落库 + 模拟盘来源放宽
-- 在 Supabase 控制台 → SQL Editor 中执行本文件；或调用 POST /api/admin/migrate 自动执行。
-- 幂等，可重复执行。
--
-- 背景 1（limitup_daily_snapshot）：东财涨停池 push2ex 只回溯约 15 个交易日（实测
-- 2026-08-27 及以前一律空池）。晋级率回测的样本窗口因此永远只有 3 周，且**不会随时间
-- 变长** —— 每天跑一次 relay_backtest，丢掉的旧数据就永远丢了。本表把每日涨停池快照
-- 落下来，回测窗口随时间自积累：跑得越久，可回测的样本越多。
--
-- 背景 2（sim_trades.source 放宽）：v5 的 CHECK 约束只有 ('manual','briefing','recommend')，
-- 但 v9 起 agent 决策采纳（/api/sim/from-plan）已用 source='agent' 写入 —— **这条路径
-- 实际上会被 DB 约束静默拒绝**（潜在 bug）。V10 一次性补上 agent 与 limitup_relay
-- （连板接力模拟建仓）。Postgres 的 CHECK 无法 IF NOT EXISTS，用 DROP CONSTRAINT IF EXISTS 配对。
-- ⚠️ 约束名是建表时 Postgres 自动生成的 `sim_trades_source_check`（小写表名+列名），
-- 若线上名字不同，DROP IF EXISTS 不报错但 ADD 会因重名冲突失败 —— 此时先查
-- information_schema.table_constraints 确认实际名字。
-- ⚠️ **必须先执行 v9（agent_decisions 表）再执行本文件的第 2 节** —— from-plan 链路
-- 依赖 v9 的表；只跑 v10 不跑 v9 时采纳接口会报「决策记录表未启用」。

-- ---------- 1. 涨停池每日快照表 ----------

CREATE TABLE IF NOT EXISTS limitup_daily_snapshot (
    id          BIGSERIAL PRIMARY KEY,
    trade_date  DATE NOT NULL,                 -- 涨停池归属交易日
    code        TEXT NOT NULL,
    name        TEXT DEFAULT '',
    boards      INTEGER NOT NULL DEFAULT 0,    -- lbc 连板数
    sector      TEXT DEFAULT '',
    seal_time   TEXT DEFAULT '',               -- 首封时间 HH:MM:SS
    last_seal_time TEXT DEFAULT '',
    break_count INTEGER DEFAULT 0,             -- 炸板次数
    seal_fund_yi NUMERIC DEFAULT 0,            -- 封单金额（亿元）
    float_mv_yi NUMERIC DEFAULT 0,             -- 流通市值（亿元）
    seal_ratio  NUMERIC DEFAULT 0,             -- 封单/流通 %
    turnover    NUMERIC DEFAULT 0,             -- 换手率 %
    amount_yi   NUMERIC DEFAULT 0,             -- 成交额（亿元）
    price       NUMERIC DEFAULT 0,
    change_pct  NUMERIC DEFAULT 0,
    stat_days   INTEGER DEFAULT 0,
    stat_boards INTEGER DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (trade_date, code)                  -- 幂等写入的天然去重键
);

CREATE INDEX IF NOT EXISTS idx_limitup_snap_date ON limitup_daily_snapshot(trade_date);
CREATE INDEX IF NOT EXISTS idx_limitup_snap_code ON limitup_daily_snapshot(code, trade_date);

ALTER TABLE limitup_daily_snapshot ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "limitup_daily_snapshot_service" ON limitup_daily_snapshot;
CREATE POLICY "limitup_daily_snapshot_service" ON limitup_daily_snapshot FOR ALL USING (true) WITH CHECK (true);

-- ---------- 2. 模拟盘来源放宽（修复 agent 写入被拒的潜在 bug） ----------

ALTER TABLE sim_trades DROP CONSTRAINT IF EXISTS sim_trades_source_check;
ALTER TABLE sim_trades ADD CONSTRAINT sim_trades_source_check
    CHECK (source IN ('manual', 'briefing', 'recommend', 'agent', 'limitup_relay'));
