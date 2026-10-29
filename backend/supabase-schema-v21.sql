-- AI 选股分析工具 · V21 迁移：暗盘 G/S 信号每日落库（明暗背离形态样本积累）
-- 在 Supabase 控制台 → SQL Editor 中执行本文件；或调用 POST /api/admin/migrate 自动执行。
-- 幂等，可重复执行。
--
-- 背景（dark_flow_daily_snapshot）：暗盘 G/S（中小单代理 · 明暗背离形态）首版只有
-- 单日横截面 —— 「持续性」（连续几日同一形态）需要时序，而个股资金流时序接口
-- （fflow/daykline）逐只请求必触发风控。自积累快照是绕开风控的正解：
-- 每日收盘形态落一行，连续性就从**本表自己的历史**里数，不再打任何额外接口。
--
-- ⚠️ 本表**不改变** G/S 的 `unsupported` 分级（未定义收益口径前不给买卖动作）。
-- 它只解决两件事：
--   1. 持续性读数（连续 N 个交易日同一形态）—— 仍是结构读数，不是买卖信号；
--   2. 样本积累 —— 未来要回测「G 形态后 N 日收益」必须先有这段历史（收益口径
--      未定义前不产出任何率值，红线不变）。
--
-- 字段与 dark_flow_service._classify 输出一一对应；mid_pct = 中单净额/成交额（%），
-- 是噪声闸门（|mid_pct| ≥ 2%）的依据。落库行只含**出信号**的票（G/S 各最多 10 只/日），
-- 量级极小（约 20 行/日），保留窗口 90 天足够看持续性。

-- ---------- 暗盘 G/S 每日快照表 ----------

CREATE TABLE IF NOT EXISTS dark_flow_daily_snapshot (
    id          BIGSERIAL PRIMARY KEY,
    signal_date DATE NOT NULL,                 -- 信号归属交易日（收盘口径）
    code        TEXT NOT NULL,
    name        TEXT DEFAULT '',
    signal      TEXT NOT NULL,                 -- 'G'（拆单吸筹嫌疑）| 'S'（拉高派发嫌疑）
    price       NUMERIC DEFAULT 0,
    change_pct  NUMERIC DEFAULT 0,
    main_net    NUMERIC DEFAULT 0,             -- 明盘（主力=超大单+大单）净额，元
    mid_net     NUMERIC DEFAULT 0,             -- 中单净额，元（暗盘代理）
    mid_pct     NUMERIC DEFAULT 0,             -- 中单净额/成交额 %（噪声闸门依据）
    amount      NUMERIC DEFAULT 0,             -- 成交额，元
    sector      TEXT DEFAULT '',
    reason      TEXT DEFAULT '',               -- 形态判词（与接口下发一致）
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (signal_date, code)                 -- 幂等写入：盘中重写覆盖为最新状态
);

CREATE INDEX IF NOT EXISTS idx_dark_flow_snap_date ON dark_flow_daily_snapshot(signal_date);
CREATE INDEX IF NOT EXISTS idx_dark_flow_snap_code ON dark_flow_daily_snapshot(code, signal_date);

ALTER TABLE dark_flow_daily_snapshot ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "dark_flow_daily_snapshot_service" ON dark_flow_daily_snapshot;
CREATE POLICY "dark_flow_daily_snapshot_service" ON dark_flow_daily_snapshot FOR ALL USING (true) WITH CHECK (true);
