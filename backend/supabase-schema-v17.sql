-- v17: 推荐算法滚动样本外校准所需原始特征
--
-- 只保存推荐生成当时已经可见的四策略分和评分配置，不保存任何未来数据。
-- excess_return / execution_status 仍由既有结算链路在 T+1 后填写。

ALTER TABLE daily_recommendations
    ADD COLUMN IF NOT EXISTS strategy_scores JSONB,
    ADD COLUMN IF NOT EXISTS scoring_profile TEXT;

COMMENT ON COLUMN daily_recommendations.strategy_scores IS
    '推荐生成时的原始策略分：momentum/trend/value/volume；用于无未来数据泄漏的样本外校准';

COMMENT ON COLUMN daily_recommendations.scoring_profile IS
    '生成该记录时使用的评分配置版本，当前为 baseline';
