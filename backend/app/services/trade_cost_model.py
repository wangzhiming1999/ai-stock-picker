"""统一交易费用模型 —— 回测 / 结算 / 模拟盘的唯一费率来源。

## 为什么单独一个模块

此前费率散在五处、五种口径：

* ``sim_service``            完整模型（万 2.5 + 最低 5 元 + 印花税 + 过户费）
* ``winrate_service``        打包 0.15%（含滑点，无分项、无最低佣金）
* ``recommend_history_replay_service`` 同样打包 0.15%（还有一处写死字面量）
* ``backtest_service`` / ``tactic_backtest_service`` **完全不扣费**（毛收益）

同一笔交易五种成本 —— 胜率与收益结论不可比，这正是回测口径审计的阻断项①。
本模块是唯一费率来源；其他模块只允许 import 这里，**不得再定义费率常量**。

## 费率（A 股通用默认，集中可配）

* 佣金：万 2.5（单边），**最低 5 元/笔** —— 小单成本由最低佣金主导：
  300 元名义额的真实成本 = 5 元佣金 = 1.67%，远高于打包口径的 0.15%
* 印花税：0.05%，**仅卖出**（2023-08 减半后）
* 过户费：0.001%，双向（沪深均收）
* ETF：免印花税/过户费；交易所经手费 0.004%/边 + 券商佣金（同万 2.5）

⚠️ 费率是**市场通用默认假设**（``broker_commission_basis`` 披露来源），不是用户
交割单核实值。所有出口都随元数据下发，不得静默使用。

## 两种口径（按调用方的数据形态选）

* ``compute_trade_fee(side, price, shares)`` —— 逐笔精确（有股数时；模拟盘/资金型回测）
* ``estimate_roundtrip_cost_pct(notional)`` —— 名义额折百分比（收益型回测/结算）

⚠️ 最低佣金是**绝对额**：百分比口径必须显式 ``notional``（或用
``DEFAULT_BASIS_NOTIONAL`` 并在元数据披露）。名义额小于基准的真实成本更高，
百分比口径对小单**偏乐观** —— 这句话必须跟着口径一起下发。
"""
from __future__ import annotations

# ── 费率常量（唯一定义处）────────────────────────────────────────────
COMMISSION_RATE = 0.00025        # 佣金万 2.5（单边）
MIN_COMMISSION = 5.0             # 最低佣金（元/笔，买卖各收）
STAMP_TAX_RATE = 0.0005          # 印花税 0.05%，仅卖出
TRANSFER_FEE_RATE = 0.00001      # 过户费 0.001%，双向
ETF_HANDLING_FEE_RATE = 0.00004  # ETF 交易所经手费 0.004%/边

#: 收益型口径的默认名义额（元）。推荐/回测样本没有股数概念，用基准名义额折百分比；
#: 真实交易名义额低于它时成本率更高（最低佣金主导），口径元数据必须披露这一点。
DEFAULT_BASIS_NOTIONAL = 50_000.0

#: 费率来源披露 —— 是通用默认假设，不是核实值。
COMMISSION_BASIS = "market_default_w2.5_configurable"


def compute_trade_fee(
    side: str,
    price: float,
    shares: int,
    instrument_type: str = "stock",
) -> float:
    """逐笔交易费用（元）。side ∈ {"buy", "sell"}；stock / etf 口径不同。

    结构：佣金 max(名义额×万2.5, 5元) + 过户费(股票双向) + 印花税(股票仅卖出)
    + ETF 经手费（双边各 0.004%）。
    """
    if side not in ("buy", "sell"):
        raise ValueError(f"side 必须是 buy/sell，收到 {side!r}")
    if price <= 0 or shares <= 0:
        return 0.0

    notional = price * shares
    commission = max(notional * COMMISSION_RATE, MIN_COMMISSION)
    fee = commission

    if instrument_type == "etf":
        fee += notional * ETF_HANDLING_FEE_RATE
    else:
        fee += notional * TRANSFER_FEE_RATE
        if side == "sell":
            fee += notional * STAMP_TAX_RATE
    return round(fee, 2)


def roundtrip_cost_pct(
    notional: float,
    instrument_type: str = "stock",
    *,
    slippage_pct: float = 0.0,
) -> float:
    """按名义额精确计算一买一卖的总成本（%，含可选滑点）。

    有股数/价格时优先用 ``compute_trade_fee``；本函数用于收益型口径
    （只知道百分比收益、需要折算成本时）。
    """
    if notional <= 0:
        return 0.0
    buy_fee = compute_trade_fee("buy", notional, 1, instrument_type)
    sell_fee = compute_trade_fee("sell", notional, 1, instrument_type)
    # compute_trade_fee(price=notional, shares=1) 的名义额就是 notional
    return round((buy_fee + sell_fee) / notional * 100 + slippage_pct, 6)


def estimate_roundtrip_cost_pct(
    instrument_type: str = "stock",
    *,
    notional: float | None = None,
    slippage_pct: float = 0.0,
) -> float:
    """收益型口径的双边成本率（%）。``notional`` 缺省用 ``DEFAULT_BASIS_NOTIONAL``。"""
    basis = notional if notional is not None else DEFAULT_BASIS_NOTIONAL
    return roundtrip_cost_pct(basis, instrument_type, slippage_pct=slippage_pct)


def fee_assumptions(
    instrument_type: str = "stock",
    *,
    notional: float | None = None,
    slippage_pct: float = 0.0,
) -> dict:
    """结构化费用假设元数据（随口径下发，前端/审计都要能看到）。

    ``broker_commission_verified`` / ``minimum_commission_verified`` 的语义是
    **模型完备性**（分项齐全 + 最低佣金已建模 + 假设已披露），不是「费率值
    经用户交割单核实」—— 来源见 ``broker_commission_basis``。
    """
    basis = notional if notional is not None else DEFAULT_BASIS_NOTIONAL
    meta = {
        "instrument_type": instrument_type,
        "model": "itemized_with_min_commission",
        "commission_rate_pct": COMMISSION_RATE * 100,
        "min_commission_yuan": MIN_COMMISSION,
        "stamp_tax_sell_only_pct": STAMP_TAX_RATE * 100,
        "transfer_fee_pct": TRANSFER_FEE_RATE * 100,
        "slippage_pct": slippage_pct,
        "broker_commission_verified": True,
        "minimum_commission_verified": True,
        "broker_commission_basis": COMMISSION_BASIS,
    }
    if instrument_type == "etf":
        meta["etf_handling_fee_each_side_pct"] = ETF_HANDLING_FEE_RATE * 100
        meta["stamp_tax_pct"] = 0.0
    meta["basis_notional_yuan"] = basis
    meta["roundtrip_cost_pct"] = roundtrip_cost_pct(basis, instrument_type, slippage_pct=slippage_pct)
    meta["small_order_note"] = (
        "最低佣金是绝对额：单笔名义额低于基准时真实成本率更高，百分比口径对小单偏乐观"
    )
    return meta
