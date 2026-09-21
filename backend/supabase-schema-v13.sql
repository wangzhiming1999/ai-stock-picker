-- AI 选股分析工具 · V13 迁移：预期价格（执行锚点）持久化
-- 在 Supabase 控制台 → SQL Editor 中执行本文件；或调用 POST /api/admin/migrate?only=v13 自动执行。
-- 幂等，可重复执行。
--
-- 背景：用户反馈「决策类文案太少，我都不知道怎么操作」「选股记录的时候记得带一个预期价格」。
-- 「预期价格」回答的是**这笔动作打算在什么价位成交**，取值来自已存在的结构位（突破位 / 回踩位）
-- 或交易所价格规则（涨停价），**不是预测价、不是目标价**。
--
-- ⚠️ 预期价格**不参与任何收益率结算**：胜率 / 溢价 / agent 计划口径一律不用它。
--    它只是执行锚点，加列纯粹是为了「事后能回看当时打算在哪成交、实际成交差多少」。
--
-- ⚠️ 表 / 列已存在时 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` 会**静默跳过**。
--    执行后建议用 information_schema.columns 核一次实际列（本项目已有过一次
--    「按代码反推列定义、写错不报错」的教训）。
--
-- 降级策略：即使本迁移没跑，后端也不会失败 ——
--   daily_recommendations.expected_price 缺失时 `save_recommendations` 会剥掉该列重试一次，
--   sim_trades.expected_price 缺失时写入被静默跳过（只丢锚点，不影响成交与胜率）。
--   两处都不会因为漏跑迁移而让推荐落库 / 模拟成交失败。

-- 1) 每日推荐：记录生成推荐时的预期成交价（回踩型取支撑买点、突破型取突破位）
ALTER TABLE daily_recommendations
    ADD COLUMN IF NOT EXISTS expected_price NUMERIC;

COMMENT ON COLUMN daily_recommendations.expected_price IS
    '预期价格（执行锚点）：计划成交价，取自结构位；不参与胜率/收益口径。NULL = 结构位样本不足';

-- 2) 模拟盘成交流水：记录下单时的预期价格，事后可算「预期 vs 实际成交」的滑点
ALTER TABLE sim_trades
    ADD COLUMN IF NOT EXISTS expected_price NUMERIC;

COMMENT ON COLUMN sim_trades.expected_price IS
    '建仓时的预期价格（计划成交价）；实际成交价见 price。两者之差即滑点，不参与胜率口径';
