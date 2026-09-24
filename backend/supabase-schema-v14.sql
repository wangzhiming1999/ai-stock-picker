-- AI 选股分析工具 · V14 迁移：推荐胜率改为「扣费 + 对比沪深300 超额」口径
-- 在 Supabase 控制台 → SQL Editor 中执行本文件（生产无 ADMIN_TOKEN，迁移只能手动跑）。
-- 全部用 IF NOT EXISTS / DROP POLICY IF EXISTS，可重复执行、幂等安全。
--
-- 背景：旧口径 hit = 次日收盘价 > 推荐价（未扣费、不对比基准），在普涨行情里虚高。
-- 新口径：net_return = 次日收益率 − 手续费；excess_return = net_return − 沪深300 同区间收益；
-- excess_return > 0 才算「赢」。结算代码（winrate_service.settle_daily_recommendations）
-- 已做列缺失静默降级，未跑本迁移前不会报错，只是 excess 字段为空、前端标注「未跑赢指数不可信」。

-- 1) 推荐记录表：新增结算口径字段
ALTER TABLE daily_recommendations
    ADD COLUMN IF NOT EXISTS benchmark_return REAL,   -- 沪深300 同区间收益率 %
    ADD COLUMN IF NOT EXISTS net_return REAL,         -- 扣费后净收益率 %（= next_return − 手续费）
    ADD COLUMN IF NOT EXISTS excess_return REAL;      -- 超额收益率 %（= net_return − benchmark_return，>0 算赢）

-- 2) 胜率快照表：新增超额口径汇总列（供看板快速加载、历史曲线）
ALTER TABLE winrate_snapshot
    ADD COLUMN IF NOT EXISTS recommend_benchmark_available BOOLEAN,
    ADD COLUMN IF NOT EXISTS recommend_excess_rate REAL,   -- 超额胜率 %（跑赢指数的样本占比）
    ADD COLUMN IF NOT EXISTS recommend_avg_excess REAL;    -- 平均超额收益 %

-- 3) 补齐 winrate_snapshot 的公开只读 RLS（与 daily_recommendations 一致）
ALTER TABLE winrate_snapshot ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "winrate_snapshot_public_read" ON winrate_snapshot;
CREATE POLICY "winrate_snapshot_public_read" ON winrate_snapshot FOR SELECT USING (true);
