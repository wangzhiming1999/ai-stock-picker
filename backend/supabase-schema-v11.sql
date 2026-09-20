-- AI 选股分析工具 · V11 迁移：补齐两张「从来没有过建表 SQL」的快照表
-- 在 Supabase 控制台 → SQL Editor 中执行本文件；或调用 POST /api/admin/migrate 自动执行。
-- 幂等，可重复执行。
--
-- 背景：`quad_snapshots` 与 `daily_recommend_snapshots` 是 quad_service（2026-09-03 上线）
-- 与 recommend_service 的持久化底座，当年**直接在控制台手动建表**，仓库里从来没有对应的
-- 建表 SQL。后果不是「读不到缓存」这么轻 —— 是**改不了**：想加列 / 加索引 / 调类型时，
-- 没有任何文件能作为「线上到底是什么结构」的依据，只能猜，或连生产库看。
-- 本文件把结构固定下来（列以代码实际读写为准）；此后任何结构变更都走新迁移文件，不再手改线上。
--
-- ⚠️ 线上若已存在同名表：`CREATE TABLE IF NOT EXISTS` 会**静默跳过**整段，既不报错也不对齐。
--    因此执行后请用 information_schema.columns 核一次实际列与下面的定义是否一致；
--    有出入就补 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS ...` 到下一个迁移文件里。
-- ⚠️ 不给 daily_recommendations.source 加 CHECK 约束（v10 给 sim_trades.source 加 CHECK
--    时，就因为代码先写了新取值而把写入静默拒掉）。本表同理：口径先靠注释与代码登记，
--    不靠 DB 约束挡 —— 挡错方向的代价是数据丢失，比脏数据更贵。

-- ---------- 1. 四维榜快照（quad_service._load_db_quad / _save_db_quad） ----------

CREATE TABLE IF NOT EXISTS quad_snapshots (
    id            BIGSERIAL PRIMARY KEY,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    snapshot_date DATE NOT NULL,                        -- 归属交易日（按最近交易日取，不是自然日）
    result        JSONB NOT NULL DEFAULT '{}'::jsonb,   -- 整份四维榜结果，写入走「先查后改/插」
    UNIQUE (snapshot_date)                              -- 每交易日一份
);

CREATE INDEX IF NOT EXISTS idx_quad_snapshots_date ON quad_snapshots(snapshot_date);

ALTER TABLE quad_snapshots ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "quad_snapshots_service" ON quad_snapshots;
CREATE POLICY "quad_snapshots_service" ON quad_snapshots
    FOR ALL USING (true) WITH CHECK (true);

-- ---------- 2. 每日推荐整组快照（recommend_service._load_db_recommendation / _save_db_recommendation） ----------

CREATE TABLE IF NOT EXISTS daily_recommend_snapshots (
    id         BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    rec_date   DATE NOT NULL,                           -- 与 daily_recommendations.rec_date 同口径
    result     JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (rec_date)
);

CREATE INDEX IF NOT EXISTS idx_daily_rec_snapshots_date ON daily_recommend_snapshots(rec_date);

ALTER TABLE daily_recommend_snapshots ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "daily_recommend_snapshots_service" ON daily_recommend_snapshots;
CREATE POLICY "daily_recommend_snapshots_service" ON daily_recommend_snapshots
    FOR ALL USING (true) WITH CHECK (true);

-- ---------- 3. 给 daily_recommendations 的两个「一名多义」列补注释（只加注释，不改结构） ----------
-- confidence 是同一个 0-10 尺度上的四种语义，靠同行 source 界定；跨 source 加总一定错。
-- 代码侧对应 recommend_service._CONFIDENCE_SOURCE_TO_DB 与 db_source()。

COMMENT ON COLUMN daily_recommendations.confidence IS
    '按 source 解释的分数槽：llm=LLM 自评把握 / rule=加权策略分（动量0.7+趋势0.3，封顶10）/ watch=strategy_score / quad=四维综合分。跨 source 不可相加。';
COMMENT ON COLUMN daily_recommendations.source IS
    '推荐来源：llm | rule | watch | quad。winrate 按此分档统计，各档口径不可比、不可相加。';
