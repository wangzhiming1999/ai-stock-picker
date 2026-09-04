# 模拟盘（Paper Trading）设计方案 v1

> 目标：在现有「持仓底座」上扩展为**可交易的模拟盘**，并闭环「推荐 → 一键模拟 → 实时盈亏 → 平仓结算 → 反哺胜率」。
> 状态：设计稿，待评审。评审通过后按分期逐步落地。

---

## 1. 定位与核心价值

模拟盘不是孤立功能，而是产品「目标只有一个：盈利」的验证器。最高价值在第 6+7 点构成的闭环：

```
推荐/简报(今天买什么)
      │  一键模拟买入
      ▼
模拟盘(sim_trades 驱动：现金/持仓/盈亏)
      │  实时市值 + 平仓结算
      ▼
收益曲线 + 已实现/未实现盈亏
      │  卖出结算结果
      ▼
反哺 V3 胜率(prediction_records.settled)  ──►  简报/推荐加权
```

- 接 V6 指令化首屏：作战简报 / 盘中节奏卡里的「买 / 卖」按钮直接生成模拟单。
- 顺手修复历史遗留：`prediction_records` 结算从没跑成 → 用模拟盘真实买卖结果驱动结算。

---

## 2. 现有底座（复用，不重写）

| 层 | 已有 | 说明 |
|----|------|------|
| 表 | `user_profiles(total_capital, risk_level)` | 虚拟本金参考值，缺可扣减现金 |
| 表 | `user_holdings(code, cost_price, shares, buy_date, note)` | 手动持仓，读取时按 spot 行情算浮盈 |
| 服务 | `portfolio_service` | mark-to-market、风险建议 |
| 服务 | `import_service` | 截图/文本批量导入持仓 |
| 接口 | `/api/portfolio/*` | CRUD + advice + import/parse |
| 前端 | `PortfolioPanel` / `ImportHoldingsModal` | 持仓展示 + 导入 |

**缺口**：无现金账户、无成交流水、无已实现盈亏、无 A股费用/T+1、无净值曲线、无「交易」动作。

---

## 3. 数据模型（新增 Supabase 表）

### 3.1 `user_profiles` 增加现金列（ALTER，不新建表）

```sql
alter table user_profiles
  add column if not exists cash numeric not null default 0;
-- 历史行：cash 默认 0，初始化时补成 total_capital（见 3.4 init）
```

### 3.2 `sim_trades`（成交流水，核心新表）

```sql
create table if not exists sim_trades (
  id            bigint generated always as identity primary key,
  user_id       uuid not null,
  code          text not null,
  name          text default '',
  side          text not null check (side in ('buy','sell')),
  price         numeric not null,
  shares        integer not null,
  fee           numeric not null default 0,
  amount        numeric not null,            -- 买: price*shares+fee；卖: price*shares-fee
  executed_at   timestamptz not null default now(),
  trade_date    date not null default current_date,  -- T+1 判定用
  source        text not null default 'manual'
                check (source in ('manual','briefing','recommend')),
  related_reco_id      text,                -- 关联推荐/预测，闭环用（可空）
  note          text default '',
  created_at    timestamptz not null default now()
);
create index if not exists idx_sim_trades_user on sim_trades(user_id, executed_at desc);
```

### 3.3 `portfolio_snapshots`（净值曲线）

```sql
create table if not exists portfolio_snapshots (
  id            bigint generated always as identity primary key,
  user_id       uuid not null,
  snapshot_date date not null default current_date,
  cash          numeric not null default 0,
  market_value  numeric not null default 0,
  total_value   numeric not null default 0,
  total_pnl     numeric not null default 0,
  total_pnl_pct numeric not null default 0,
  positions_cnt integer not null default 0,
  created_at    timestamptz not null default now(),
  unique (user_id, snapshot_date)
);
```

> RLS：现有表走 service client 绕过 RLS（见 `portfolio_service`）。新建表保持同样策略（暂不加 RLS 策略，归属由后端 `user_id` 隔离保证）。如需启用 RLS，后续补 `using (user_id = auth.uid())` 策略。

### 3.4 关系决策

- **MVP 模拟盘完全由 `sim_trades` 驱动**，`sim_positions` 不落表，改为查询时聚合（平均成本法，单一数据源，避免双写不一致）。
- 现有 `user_holdings`（手动/导入真实持仓）作为「真实盘视图」保留，暂不与模拟盘合并；后续可加「导入为模拟初始持仓」迁移。
- `sim_account` 不新建表，现金直接放 `user_profiles.cash`。

---

## 4. 交易引擎（新增 `sim_service.py`）

### 4.1 买入 `buy(user_id, code, shares, price=None)`

1. `price` 默认取实时 spot：`data_service.get_spot_quote([code])[0].price`；允许手动指定。
2. 费用：`fee = 佣金(price*shares*0.00025, 最低 5 元) + 过户费(price*shares*0.00001)`（买无印花税）。
3. 校验：`cash >= price*shares + fee`，否则 400。
4. 扣 `cash`，写 `sim_trades(side=buy, amount=price*shares+fee)`。
5. 返回更新后账户 + 该代码新持仓（平均成本重算）。

### 4.2 卖出 `sell(user_id, code, shares, price=None)`

1. `price` 默认取 spot。
2. **T+1**：`trade_date = current_date` 的买入不允许当日卖（按 `sim_trades.trade_date` 判定）；MVP 可先放开，P1 默认开启（参数 `enforce_t1`）。
3. 费用：`fee = 佣金 + 过户费 + 印花税(price*shares*0.0005)`。
4. 校验：持仓可用股数 ≥ `shares`（可用 = 总买 - 总卖，排除当日买入）。
5. 加 `cash`，写 `sim_trades(side=sell, amount=price*shares-fee)`。
6. 平仓部分 `realized_pnl = (price - avg_cost)*shares - fee`（按平均成本简化）。

### 4.3 盈亏

- 未实现 = `(current_price - avg_cost) * shares`（聚合持仓时按 spot 算）。
- 已实现 = Σ 卖出 `realized_pnl`。
- 净值 = `cash + Σ(market_value)`。
- `avg_cost` = (Σ买入金额 - Σ卖出回收) / 剩余股数（或简单累计买入成本 / 剩余股数；MVP 用累计买入成本/剩余股数）。

### 4.4 净值曲线

- 复用 `daily` cron：收盘后写 `portfolio_snapshots`（cash + market_value + pnl）。
- 前端读 `portfolio_snapshots` 画 echarts 折线；缺失日期可按时段末值补。

---

## 5. API（新增 `/api/sim/*`）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/sim/account/init` | 设本金/风险，初始化 `cash = total_capital` |
| GET | `/api/sim/account` | cash / total_capital / total_value / total_pnl / total_pnl_pct / positions_cnt |
| POST | `/api/sim/trade` | `{code, side, shares, price?}` 买卖 |
| GET | `/api/sim/positions` | 聚合持仓：code/name/avg_cost/current_price/shares/market_value/unrealized_pnl/pnl_pct |
| GET | `/api/sim/trades` | 成交流水（分页，按 executed_at desc） |
| GET | `/api/sim/performance` | 净值曲线 + 胜率统计（按 source 分组） |
| POST | `/api/sim/reset` | 清零重来（安全网，确认后执行） |

鉴权复用 `portfolio.py` 的 `_require_user`（Bearer JWT → `user_id`）。

---

## 6. 前端 UI

- **模拟盘面板**：现金 / 市值 / 总盈亏 / 当日盈亏 四卡片。
- **持仓列表**：代码 / 名称 / 成本 / 现价 / 股数 / 市值 / 浮盈浮亏 / 买卖按钮（复用 `PortfolioPanel` 改造）。
- **买卖弹窗**：方向 / 代码 / 股数 / 价格(默认现价) / 预估费用 / 确认；复用 `ImportHoldingsModal` 的交互模式。
- **成交记录**：时间线列表。
- **收益曲线**：echarts 折线（前端已装 echarts）。
- **一键模拟**：作战简报 / 盘中节奏卡的「买 / 卖」按钮 → 打开买卖弹窗预填代码（P2 闭环）。

---

## 7. 分期

- **P0（MVP）**：`sim_trades` + `cash` + buy/sell + 持仓聚合 + 盈亏 + 前端面板/买卖。跑通可交易模拟盘。
- **P1**：`portfolio_snapshots` + daily cron 写入 + 成交记录 + 收益统计 + T+1 默认开启。
- **P2（闭环）**：简报/推荐一键模拟（买卖按钮预填）+ 卖出结算写 `prediction_records.settled`（修复 V3 结算断点）+ 胜率反哺。

---

## 8. 风险与待确认

1. **成交价语义**：默认实时 spot（盘中介入）还是次日开盘？建议默认 spot、允许手动覆盖。
2. **T+1**：MVP 先放开，P1 默认开启（参数 `enforce_t1`）。
3. **Supabase 建表**：SQL 由我出，需你在控制台执行（同 `alert` 表流程，无 service key 我直连不了）。
4. **费用参数**：佣金率 0.00025 / 最低 5 元 / 印花 0.0005 / 过户 0.00001 取 A股通用值，是否贴合你的券商？做成可配置。
5. **user_holdings vs sim_trades**：MVP 模拟盘独立用 `sim_trades`；现有持仓导入作为真实盘视图保留，不强制合并。
6. **安全网**：`/api/sim/reset` 清零需二次确认；首次动 schema 前先 `py_compile` + `tsc -b` 全量校验。

---

## 9. 与现有模块衔接

- **V6 指令化首屏**：买卖按钮直接生成模拟单（P2）。
- **V3 胜率**：`sim_trades` 卖出结算 → 写 `prediction_records.settled`，修复结算断点（P2）。
- **V6.1 胜率反哺**：模拟盘胜率 → 简报/推荐加权（P2 之后）。
- **预警中心 V6**：持仓触发预警 → 可在模拟盘提示减仓动作（后续）。
