-- v16: 每日推荐按真实触发成交结算
--
-- 推荐卡给的是 T+1 条件单：回踩价未到、突破价未穿越时并没有交易。
-- 旧结算却默认按推荐日收盘价已经买入，导致未触发计划也进入胜率分母。
-- 新字段记录是否成交以及实际用于结算的入场价。

ALTER TABLE daily_recommendations
    ADD COLUMN IF NOT EXISTS execution_status TEXT,
    ADD COLUMN IF NOT EXISTS entry_price NUMERIC;

COMMENT ON COLUMN daily_recommendations.execution_status IS
    'T+1 执行状态：filled=触发成交，not_triggered=条件未到，unverifiable=OHLC不足，legacy=旧口径';

COMMENT ON COLUMN daily_recommendations.entry_price IS
    '真实结算入场价：回踩限价取 min(触发价,次日开盘)，突破单取 max(触发价,次日开盘)';
