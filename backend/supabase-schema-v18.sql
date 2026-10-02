-- v18: recommendation-time feature snapshots for future point-in-time replay
--
-- Values are copied only from data visible when the recommendation is generated.
-- Outcome fields remain in the existing settlement columns and are never stored here.

ALTER TABLE daily_recommendations
    ADD COLUMN IF NOT EXISTS feature_snapshot JSONB;

COMMENT ON COLUMN daily_recommendations.feature_snapshot IS
    'Signal-time PE/PB/turnover/market cap and stable board class; excludes all future outcomes';
