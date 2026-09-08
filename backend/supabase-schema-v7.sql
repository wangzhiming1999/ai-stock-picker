-- V7: 模拟盘交易原子化。账户锁、余额/持仓校验、现金变更和流水写入在同一事务完成。
CREATE OR REPLACE FUNCTION execute_sim_trade(
    p_user_id TEXT, p_code TEXT, p_name TEXT, p_side TEXT, p_price NUMERIC,
    p_shares INTEGER, p_fee NUMERIC, p_amount NUMERIC, p_source TEXT,
    p_related_reco_id TEXT, p_note TEXT, p_trade_date DATE
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    v_cash NUMERIC;
    v_available INTEGER;
    v_trade sim_trades%ROWTYPE;
BEGIN
    IF p_side NOT IN ('buy', 'sell') OR p_shares <= 0 OR p_shares % 100 <> 0 OR p_price <= 0 THEN
        RAISE EXCEPTION '交易参数无效';
    END IF;

    SELECT cash INTO v_cash FROM user_profiles WHERE user_id = p_user_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION '模拟账户不存在'; END IF;
    v_cash := COALESCE(v_cash, 0);

    IF p_side = 'buy' THEN
        IF v_cash < p_amount THEN RAISE EXCEPTION '现金不足'; END IF;
        UPDATE user_profiles SET cash = v_cash - p_amount, updated_at = NOW() WHERE user_id = p_user_id;
    ELSE
        SELECT COALESCE(SUM(CASE WHEN side = 'buy' THEN shares ELSE -shares END), 0)
             - COALESCE(SUM(CASE WHEN side = 'buy' AND trade_date = p_trade_date THEN shares ELSE 0 END), 0)
        INTO v_available FROM sim_trades WHERE user_id = p_user_id AND code = p_code;
        IF v_available < p_shares THEN RAISE EXCEPTION '可用股数不足（含 T+1 限制）'; END IF;
        UPDATE user_profiles SET cash = v_cash + p_amount, updated_at = NOW() WHERE user_id = p_user_id;
    END IF;

    INSERT INTO sim_trades (
        user_id, code, name, side, price, shares, fee, amount,
        source, related_reco_id, note, trade_date
    ) VALUES (
        p_user_id, p_code, COALESCE(p_name, ''), p_side, p_price, p_shares, p_fee, p_amount,
        p_source, p_related_reco_id, COALESCE(p_note, ''), p_trade_date
    ) RETURNING * INTO v_trade;

    RETURN jsonb_build_object('trade', to_jsonb(v_trade), 'cash',
        CASE WHEN p_side = 'buy' THEN v_cash - p_amount ELSE v_cash + p_amount END);
END;
$$;

REVOKE ALL ON FUNCTION execute_sim_trade(TEXT,TEXT,TEXT,TEXT,NUMERIC,INTEGER,NUMERIC,NUMERIC,TEXT,TEXT,TEXT,DATE) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION execute_sim_trade(TEXT,TEXT,TEXT,TEXT,NUMERIC,INTEGER,NUMERIC,NUMERIC,TEXT,TEXT,TEXT,DATE) TO service_role;
