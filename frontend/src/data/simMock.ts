/**
 * 模拟盘兜底数据（SimPanel 降级用）
 *
 * 用途：SimPanel 采用「真实优先 + mock 兜底」策略——并行请求
 * /api/sim/{account,positions,trades,performance}，任一失败（后端缺表 / 500 /
 * 网络异常）时降级展示本文件数据，并在面板标注「演示数据」，避免红屏报错。
 * 后端恢复后会自动切回真实数据，无需改动代码。
 *
 * 内部一致性自查：
 *   initial 100,000 + realized 2,000 + unrealized 700 = total_value 102,700
 *   cash 62,100 + market_value 40,600 = total_value 102,700
 *
 * 成交价按 A 股费用规则（佣金 max(0.025%, 5) + 过户 0.001% + 卖方印花 0.05%）近似取整。
 */
import type {
  SimAccount,
  SimPerformance,
  SimPositionsData,
  SimTrade,
  SimTradesData,
} from "../types";

/** 账户总览 */
export const MOCK_SIM_ACCOUNT: SimAccount = {
  cash: 62100,
  total_capital: 100000,
  market_value: 40600,
  total_value: 102700,
  realized_pnl: 2000,
  unrealized_pnl: 700,
  total_pnl: 2700,
  total_pnl_pct: 2.7,
  positions_cnt: 3,
  initialized: true,
};

/** 聚合持仓（3 只） */
export const MOCK_SIM_POSITIONS: SimPositionsData = {
  positions: [
    {
      code: "600519",
      name: "贵州茅台",
      shares: 10,
      avg_cost: 1620.0,
      current_price: 1680.0,
      market_value: 16800,
      unrealized_pnl: 600,
      pnl_pct: 3.7,
    },
    {
      code: "000858",
      name: "五粮液",
      shares: 100,
      avg_cost: 138.0,
      current_price: 142.0,
      market_value: 14200,
      unrealized_pnl: 400,
      pnl_pct: 2.9,
    },
    {
      code: "300750",
      name: "宁德时代",
      shares: 50,
      avg_cost: 198.0,
      current_price: 192.0,
      market_value: 9600,
      unrealized_pnl: -300,
      pnl_pct: -3.03,
    },
  ],
  realized_pnl: 2000,
  open_count: 3,
};

/** 近期成交流水（6 笔） */
export const MOCK_SIM_TRADES: SimTradesData = {
  total: 6,
  limit: 30,
  offset: 0,
  trades: [
    {
      id: 1,
      user_id: "demo",
      code: "600519",
      name: "贵州茅台",
      side: "buy",
      price: 1620.0,
      shares: 10,
      fee: 5.16,
      amount: 16205.16,
      executed_at: "2026-08-25T09:35:12",
      trade_date: "2026-08-25",
      source: "manual",
    },
    {
      id: 2,
      user_id: "demo",
      code: "000858",
      name: "五粮液",
      side: "buy",
      price: 138.0,
      shares: 100,
      fee: 5.14,
      amount: 13805.14,
      executed_at: "2026-08-28T10:15:33",
      trade_date: "2026-08-28",
      source: "manual",
    },
    {
      id: 3,
      user_id: "demo",
      code: "300750",
      name: "宁德时代",
      side: "buy",
      price: 198.0,
      shares: 50,
      fee: 5.1,
      amount: 9905.1,
      executed_at: "2026-09-01T14:20:05",
      trade_date: "2026-09-01",
      source: "manual",
    },
    {
      id: 4,
      user_id: "demo",
      code: "000858",
      name: "五粮液",
      side: "sell",
      price: 146.0,
      shares: 30,
      fee: 9.31,
      amount: 4370.69,
      executed_at: "2026-09-02T11:02:48",
      trade_date: "2026-09-02",
      source: "manual",
    },
    {
      id: 5,
      user_id: "demo",
      code: "600519",
      name: "贵州茅台",
      side: "sell",
      price: 1750.0,
      shares: 5,
      fee: 14.13,
      amount: 8735.87,
      executed_at: "2026-09-03T13:45:21",
      trade_date: "2026-09-03",
      source: "manual",
    },
    {
      id: 6,
      user_id: "demo",
      code: "300750",
      name: "宁德时代",
      side: "sell",
      price: 220.0,
      shares: 10,
      fee: 12.11,
      amount: 2187.89,
      executed_at: "2026-09-04T10:28:09",
      trade_date: "2026-09-04",
      source: "manual",
    },
  ] satisfies SimTrade[],
};

/** 净值曲线（5 个交易日快照） */
export const MOCK_SIM_PERFORMANCE: SimPerformance = {
  snapshots: [
    { date: "2026-08-25", total_value: 100000, total_pnl: 0, total_pnl_pct: 0, cash: 83789.7, market_value: 16210.3 },
    { date: "2026-08-28", total_value: 100520, total_pnl: 520, total_pnl_pct: 0.52, cash: 69979.86, market_value: 30540.14 },
    { date: "2026-09-01", total_value: 101200, total_pnl: 1200, total_pnl_pct: 1.2, cash: 60064.16, market_value: 41135.84 },
    { date: "2026-09-03", total_value: 102080, total_pnl: 2080, total_pnl_pct: 2.08, cash: 64370.03, market_value: 37709.97 },
    { date: "2026-09-04", total_value: 102700, total_pnl: 2700, total_pnl_pct: 2.7, cash: 62100, market_value: 40600 },
  ],
  realized_pnl: 2000,
  unrealized_pnl: 700,
  total_pnl: 2700,
  total_pnl_pct: 2.7,
  by_source: {
    manual: { trades: 6, buy_shares: 160, sell_shares: 45, buy_amount: 39915.4, sell_amount: 15294.45 },
  },
};