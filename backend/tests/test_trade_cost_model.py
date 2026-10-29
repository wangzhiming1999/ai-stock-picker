"""统一交易费用模型测试。

守卫口径：**撤掉修复必须变红** ——
最低佣金 / 印花税仅卖出 / ETF 免税 / 小单成本率高于打包值，逐条对着实现打。
"""
from __future__ import annotations

import pytest

from app.services import trade_cost_model as M


class FeeStructureTests:
    def test_min_commission_applies_to_small_orders(self) -> None:
        """300 元名义额：佣金按最低 5 元收，不是 0.075 元。撤掉 MIN_COMMISSION 即红。"""
        fee = M.compute_trade_fee("buy", price=3.0, shares=100)
        # 5 元佣金 + 300×0.001% 过户费 = 5.003
        assert fee == pytest.approx(5.0, abs=0.01)

    def test_large_order_pays_proportional_commission(self) -> None:
        """10 万元名义额：佣金 25 元 > 最低 5 元，按比例收。"""
        fee = M.compute_trade_fee("buy", price=100.0, shares=1000)
        assert fee == pytest.approx(25.0 + 1.0, abs=0.01)  # 佣金 25 + 过户费 1

    def test_stamp_tax_only_on_sell(self) -> None:
        """印花税只对卖出征收。买入收印花税即红。"""
        buy = M.compute_trade_fee("buy", price=10.0, shares=1000)
        sell = M.compute_trade_fee("sell", price=10.0, shares=1000)
        assert sell - buy == pytest.approx(10_000 * 0.0005, abs=0.01)

    def test_etf_pays_no_stamp_no_transfer_but_handling_fee(self) -> None:
        """ETF：免印花税/过户费，收经手费 0.004%/边（1 万名义额佣金 2.5 元触发最低 5 元）。"""
        buy = M.compute_trade_fee("buy", price=10.0, shares=1000, instrument_type="etf")
        # 佣金 max(2.5, 5)=5 + 经手费 10000×0.00004=0.4
        assert buy == pytest.approx(5.4, abs=0.01)
        sell = M.compute_trade_fee("sell", price=10.0, shares=1000, instrument_type="etf")
        assert sell == pytest.approx(5.4, abs=0.01)  # 与买入同价 —— 无印花税

    def test_invalid_side_rejected(self) -> None:
        with pytest.raises(ValueError):
            M.compute_trade_fee("hold", 10.0, 100)


class RoundtripTests:
    def test_roundtrip_small_order_cost_rate_beats_flat_assumption(self) -> None:
        """300 元名义额双边成本率 ≈ 3.3% —— 远高于打包 0.15%，这正是阻断项①的实证。"""
        rate = M.roundtrip_cost_pct(300.0)
        assert rate > 1.0
        # 双边最低佣金 10 元 + 过户/印花 ≈ 10.13 元 / 300 = 3.38%
        assert rate == pytest.approx(3.38, abs=0.1)

    def test_roundtrip_at_basis_notional_matches_itemized(self) -> None:
        """基准名义额的双边成本与分项费用对账一致。"""
        notional = M.DEFAULT_BASIS_NOTIONAL
        itemized = (
            M.compute_trade_fee("buy", notional, 1)
            + M.compute_trade_fee("sell", notional, 1)
        ) / notional * 100
        assert M.roundtrip_cost_pct(notional) == pytest.approx(itemized, abs=1e-6)

    def test_slippage_is_additive_and_optional(self) -> None:
        base = M.roundtrip_cost_pct(100_000.0)
        with_slip = M.roundtrip_cost_pct(100_000.0, slippage_pct=0.05)
        assert with_slip == pytest.approx(base + 0.05, abs=1e-6)

    def test_estimate_uses_default_basis_and_discloses(self) -> None:
        rate = M.estimate_roundtrip_cost_pct()
        assert rate == M.roundtrip_cost_pct(M.DEFAULT_BASIS_NOTIONAL)
        meta = M.fee_assumptions()
        assert meta["basis_notional_yuan"] == M.DEFAULT_BASIS_NOTIONAL
        assert "偏乐观" in meta["small_order_note"]


class AssumptionMetaTests:
    def test_meta_declares_itemized_model_and_basis(self) -> None:
        """fee_model_verified 的依据：分项齐全 + 最低佣金建模 + 假设来源披露。"""
        meta = M.fee_assumptions("stock", slippage_pct=0.05)
        assert meta["model"] == "itemized_with_min_commission"
        assert meta["min_commission_yuan"] == 5.0
        assert meta["broker_commission_verified"] is True
        assert meta["minimum_commission_verified"] is True
        assert meta["broker_commission_basis"] == M.COMMISSION_BASIS
        assert meta["stamp_tax_sell_only_pct"] == 0.05
        assert meta["slippage_pct"] == 0.05

    def test_etf_meta_zero_stamp(self) -> None:
        meta = M.fee_assumptions("etf")
        assert meta["stamp_tax_pct"] == 0.0
        assert meta["etf_handling_fee_each_side_pct"] == 0.004
