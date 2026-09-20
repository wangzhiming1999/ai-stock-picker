# AI 选股分析工具（AI Stock Picker）

> LLM 驱动的 A 股选股分析平台，**目标只有一个：盈利**。
> 把每个关键交易时点变成「打开就知道今天怎么操作」的指令卡——早盘买什么、尾盘怎么挂单、持仓怎么调。

AI 选股分析工具用 AI 结合实时行情、K 线趋势与最新新闻，输出**基本面 / 技术面 / 资金面 / 消息面**四维评分与操作建议；并在此之上构建了一套「推荐 → 模拟盘验证 → 胜率反哺」的量化投研闭环。支持行业板块扫描、策略选股、策略回测、持仓管理、模拟盘交易、预警提醒与每日作战简报。

---

## ✨ 功能特性

### 分析 & 选股
- **AI 四维分析**：SSE 流式输出分析过程，四维综合评分 + 风险提示 + 操作建议
- **双模式**：配置 DeepSeek API Key 走 LLM 深度分析；未配置自动降级为本地规则评分
- **市场扫描**：49 个行业板块列表 + 全市场条件扫描（价格 / 涨幅 / 成交额过滤），一键送入分析
- **策略选股**：动量 / 趋势 / 低估值 / 放量 / 综合 五种策略一键扫描
- **实战形态**：多周期共振 / 揉搓线 / 断头铡刀 / 地量见地价 / 天量见天价 / 分时顶背离 六条可复核技巧，逐条条件展示（全部成立才命中）
- **形态回测验证**：walk-forward 检验六条技巧的历史表现，方向化胜率 + 同区间基准对比 + 命中去重，样本不足不给结论
- **技术信号**：压力位 / 支撑位 / 买入点 / 卖出点 / 止损位 / 风险收益比 / 信号强度
- **明日大盘推衍**：上证指数技术信号 + LLM 次日走势预测，卡片内嵌指数走势图

### 数据闭环 & 验证
- **每日收盘推荐**：策略候选 + LLM 精选 10 只（含推荐理由 / 置信分），按交易日缓存
- **胜率看板**：预测命中率 + 推荐次日胜率（每个数字随接口下发自己的**测量口径**，见「口径与证据」）
- **策略回测引擎**：历史 K 线 → 策略信号 → 模拟调仓 → 收益 / 回撤 / 夏普 / 胜率，对比沪深 300 基准
- **模拟盘（Paper Trading）**：现金账户 + 买卖成交 + 持仓聚合（平均成本）+ 实时盈亏 + 净值曲线，支持 A 股费用与 T+1

### 持仓 & 盯盘
- **持仓管理**：用户持仓 CRUD（按用户隔离）+ 风险等级（保守 / 稳健 / 进取 / 激进）+ 总资金 + 持仓建议 + 盈亏展示
- **自选股看板**：增删 / 批量导入 / 实时涨跌
- **盘前 / 尾盘机会**：早盘竞价（9:15–9:30）强势标的、尾盘（14:45–15:00）异动标的
- **预警中心（站内提醒）**：价格 / 止损 / 买点 / 支撑压力突破 / 放量异动 五类规则，事件去重与未读角标

### 指令化体验
- **今日作战简报卡**：时点感知 + 大方向 + 建议仓位 + 早盘买什么 + 尾盘怎么操作（首屏默认只留这张卡）
- **盘中节奏卡**：盘前预读（大方向 + 隔夜美股三大指数）/ 尾盘挂单建议（减仓挂现价上方、加仓回踩支撑）+ 收盘前紧急条
- **交易日历**：盘前 / 集合竞价 / 早盘 / 午休 / 午后 / 尾盘 / 收盘后 时段映射，预测与推荐缓存按交易日对齐

### 工程 & 部署
- **登录注册**：Supabase Auth（cookie + localStorage 双重持久化 + 自动刷新）
- **部署就绪**：CORS 白名单 / 接口限流中间件 / Dockerfile + docker-compose / Vercel Serverless
- **移动端适配**：底部 Tab 导航 + 响应式布局

---

## 🏗️ 技术栈

| 层 | 技术 |
|----|------|
| 前端 | React 18 · Vite 6 · TypeScript · Tailwind CSS 3 · ECharts 5 · framer-motion · lucide-react · sonner · @supabase/supabase-js |
| 后端 | Python 3.11 · FastAPI · akshare（A 股数据）· DeepSeek（OpenAI 兼容接口）· Supabase（Postgres + Auth） |
| 存储 | **双持久化**：Supabase（用户 / 持仓 / 预测 / 自选 / 预警 / 模拟盘等）+ SQLite（本地分析历史，未接 Supabase 时降级） |
| 交互 | REST + SSE 流式分析进度 |
| 部署 | Docker / Vercel（前后端分离） |

---

## 🚀 快速开始

### 前置条件
- Node.js 18+ 与 Python 3.11+
- （可选）DeepSeek API Key —— 用于 LLM 深度分析，不配置则走本地规则评分
- （可选）Supabase 项目 —— 用于登录、持仓、预测、自选、预警、模拟盘等完整能力

### 1. 本地运行（最小可用）

后端使用 SQLite 保存分析历史，无需 Supabase 即可体验核心分析能力：

```bash
# 后端
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # 可选：填入 DEEPSEEK_API_KEY
python -m app.main          # http://localhost:8000

# 前端（另开终端）
cd frontend
npm install
npm run dev                 # http://localhost:5173
```

### 2. 接入 Supabase（完整能力）

1. 在 Supabase 新建项目，按顺序执行 `backend/supabase-schema.sql`（v1）及 `supabase-schema-v2.sql` … `supabase-schema-v10.sql`；
   或部署后端后调用 `POST /api/admin/migrate` 自动执行全部迁移（需先配置 `ADMIN_TOKEN` 与 `SUPABASE_MANAGEMENT_API_KEY`）。
   所有脚本均幂等，可重复执行。v8（`market_source_state`）/ v9（`agent_decisions`）/ v10（`limitup_daily_snapshot` + `sim_trades.source` 放宽）可选：不执行则对应功能静默降级。
2. 在项目设置中获取 URL 与 anon / service_role Key，写入 `backend/.env`：
   ```ini
   SUPABASE_URL=https://xxxx.supabase.co
   SUPABASE_ANON_KEY=eyJ...
   SUPABASE_SERVICE_KEY=eyJ...   # 仅服务端使用，勿暴露给前端
   ```
3. 重启后端，`GET /api/health` 返回 `"supabase": true` 即生效。

### 环境变量（backend/.env）

| 变量 | 说明 |
|------|------|
| `DEEPSEEK_API_KEY` | DeepSeek Key，留空则本地规则评分 |
| `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL` | 兼容 OpenAI 的端点与模型（默认 `api.deepseek.com` / `deepseek-chat`） |
| `VL_API_KEY` / `VL_BASE_URL` / `VL_MODEL` | 视觉模型（持仓截图识别），默认智谱 GLM-4V-Flash |
| `LLM_MODE` | `auto`（默认）/ `mock`（强制规则）/ `real`（强制 LLM） |
| `SUPABASE_URL` / `SUPABASE_ANON_KEY` / `SUPABASE_SERVICE_KEY` | Supabase 配置（配置后启用登录与持久化） |
| `ALLOWED_ORIGINS` | 生产环境 CORS 白名单，逗号分隔 |
| `ENABLE_RATE_LIMIT` | 是否开启接口限流（`true` / `false`） |
| `DATABASE_PATH` | SQLite 路径（未接 Supabase 时使用） |
| `ADMIN_TOKEN` | 运维端点 `/api/admin/*` 鉴权令牌，留空则禁用该组接口 |
| `SUPABASE_MANAGEMENT_API_KEY` | Supabase Management API Key，供 `/api/admin/migrate` 自动建表用 |
| `DATABASE_URL` | Postgres 直连串，`/api/admin/migrate` 执行 SQL 的备选方式 |

---

## 🧪 测试与校验

改动后至少跑一遍下面四步（CI 也是这四步，见 `.github/workflows/ci.yml`）：

```bash
# 后端（490 个用例）
cd backend
pip install -r requirements-dev.txt   # 含 pytest / pytest-asyncio
pytest -q

# 前端
cd frontend
npm run typecheck   # tsc --noEmit -p tsconfig.app.json && -p tsconfig.node.json
npm test            # node --test（内置 runner，无需额外依赖）
npm run build       # tsc -b && vite build
```

**两个必须知道的坑**：

| 坑 | 说明 |
|---|---|
| 类型检查必须用 `tsconfig.app.json` | 根 `tsconfig.json` 是 `{"files":[],"references":[...]}` 的项目引用模式，`tsc --noEmit -p .` **一个文件都不检查、永远 exit 0** |
| `vite build` 不检查类型 | esbuild 只转译不做类型校验，**build 通过 ≠ 类型正确**，两个都要跑 |

> 前端单测用 Node 内置 `node --test`（需 Node ≥ 22.18，靠内置类型擦除直接跑 `.ts`），不引入 vitest。

---

## 📐 口径与证据（两条硬约定）

这一节约束的不是「怎么算」，而是「算出来的数字能不能拿来下结论 」。
用户反馈的「数据不准确」有两类：一类是数字算错，一类是**数字没错但可信度没被区分**。
下面两条针对后者，改动相关代码前请先读完。

### 1. 每个「率」都必须登记测量口径

「验证」页同屏会出现 4 个都叫「胜率 / 命中率」的数字，它们的标的 / 持有期 / 分类数 / 有无基准全都不一样：

| 出处 | 标的 | 持有期 | 分类数 | 基准 |
|---|---|---|---|---|
| 大盘推衍 | 上证指数 | 预测日当日 | 3（含震荡，±0.5% 中性带） | 无 |
| 每日推荐 | 个股 | T+1 收盘 | 2 | 无 |
| 策略回测 | 组合 | 每个调仓期 | 2 | 沪深300 |
| 形态回测 | 个股 | N 个交易日 | 2（按方向） | 同区间同持有期 |

**它们不可比较、不可相加。** 口径定义集中在 `backend/app/services/calibers.py`，
随接口一起下发（`caliber` + `caliber_note`），前端只展示不自己解释，渲染统一走
`frontend/src/components/CaliberNote.tsx`。

> 新增任何「率」之前，先在 `calibers.py` 登记口径；**没有登记的百分比不允许出现在界面上**。

### 2. 形态命中 ≠ 形态有效：证据闸门

`services/tactic_evidence.py` 是形态可信度的**唯一来源**，按回测结果分 5 档：

| tier | 判定 | 能否进入买卖点 |
|---|---|---|
| `verified` | n ≥ 30 且 \|z\| ≥ 1.96 且各持有期收益超额为正 | ✅ |
| `preliminary` | n < 30，但超额方向一致为正 | ❌（只作线索，带「初步」角标） |
| `unsupported` | n ≥ 30 未达显著，或超额为负 | ❌ |
| `unknown` | 尚未用当前实现回测过 | ❌ |
| `not_testable` | 当前数据源无法回测 | ❌ |

`_pack()` 给每条形态结果挂 `evidence` / `executable`（= 命中 && 证据达标）/ `gate_note`，
所以扫描 / 深度分析 / 盯盘 / 持仓 / 简报的结论必然一致；前端未验证的命中**不使用方向色**
（红绿只表达方向，用它渲染未验证形态会被读成「该动手了」），改中性「观察」角标。
`pattern_service.ESCALATE_SELL_KEYS` 也由这张表推导，不再手写。

> ⚠️ 当前（2026-09-16 复跑）**没有任何形态达到 `verified`**，因此全部命中都进观察池。
> 想放开某条形态，改 `tactic_evidence.EVIDENCE` 里的 tier 并写明依据 —— 不要直接改闸门代码。

**证据快照**：42 只行业分散大中盘 · 每只 640 根日线 · 240 个评估日 · 持有 5/10/20 日，
随 `GET /api/market/tactic-evidence` 返回。重跑 `POST /api/backtest/tactic` 后需同步更新表中数字。

---

## 📁 项目结构

```
ai-stock-picker/
├── backend/
│   ├── app/
│   │   ├── main.py               # FastAPI 入口（CORS/限流/健康检查/路由注册）
│   │   ├── config.py             # pydantic-settings 配置
│   │   ├── models.py             # 数据模型
│   │   ├── store.py              # SQLite 本地分析历史
│   │   ├── routes/               # 18 个路由模块（见下）
│   │   └── services/            # 34 个服务模块（见下）
│   ├── supabase-schema*.sql      # 建表脚本 v1–v10（幂等，可重复执行）
│   ├── requirements.txt
│   └── vercel.json
├── frontend/
│   └── src/
│       ├── App.tsx              # 3 入口主框架：今日作战 / 选机会 / 持仓（深度分析走全局抽屉）
│       ├── api/                 # client / auth / supabase
│       ├── auth/AuthContext.tsx # 登录态
│       ├── components/          # 20+ 组件（简报/推荐/扫描/回测/持仓/模拟盘/预警…）
│       └── lib/                 # dates / motion / usePersist / safe
├── docs/
│   └── sim-trading-plan.md      # 模拟盘设计文档
├── Dockerfile · docker-compose.yml
├── README.md · CHANGELOG.md · ROADMAP.md
```

**后端路由**（`app/routes`）：
`stock`（行情 / K 线 / 新闻）· `analysis`（选股分析 SSE）· `market`（板块 / 扫描 / 推荐 / 大盘推衍 / 机会）· `history`（历史批次）· `auth`（登录注册）· `cron`（每日结算 / 扫描）· `alerts`（预警中心）· `backtest`（回测）· `portfolio`（持仓）· `sim`（模拟盘）· `watchlist`（自选股）· `briefing`（今日简报）· `quad`（榜单）· `monitor`（监控）· `limitup`（连板梯队 / 涨停情绪）· `limitdown`（跌停池 / 次日修复收益）

**后端服务**（`app/services`）：
`data_service`（akshare 行情 / 新闻）· `llm_service`（DeepSeek + 规则兜底）· `signal_service`（技术信号）· `market_prediction`（大盘推衍）· `recommend_service`（每日推荐）· `backtest_service` · `portfolio_service` · `sim_service`（交易引擎）· `watchlist_service` · `alert_service` · `winrate_service`（胜率）· `trade_calendar_service`（交易日历）· `opportunity_service`（盘前 / 尾盘机会）· `pattern_service`（实战形态）· `quad_service` · `briefing_service` · `import_service`（持仓截图 / 文本导入）· `supabase_store`（Supabase 持久化）· `agent_decision_service`（agent 决策闭环）· `debate_service`（多空研究员对辩）· `limitup_service`（涨停池 / 连板梯队 / 晋级率）· `limitdown_service`（跌停池 / 连跌梯队 / 次日修复收益回测）· `tactic_evidence`（证据等级闸门）· `calibers`（统计口径登记表）· `evidence_ledger`（证据台账只读聚合）

---

## 🔌 API 概览

完整接口见各路由模块。代表性端点：

| 模块 | 方法 | 路径 | 说明 |
|------|------|------|------|
| 健康 | GET | `/api/health` | 健康检查（模式 / Supabase / 限流状态） |
| 行情 | GET | `/api/stock/{code}` | 个股行情 + K 线 |
| 行情 | GET | `/api/stock/{code}/news` | 个股新闻 |
| 分析 | POST | `/api/analysis/stocks` | 批量选股分析（SSE 流式） |
| 市场 | GET | `/api/market/industries` | 行业板块列表 |
| 市场 | POST | `/api/market/scan` | 全市场扫描选股 |
| 市场 | POST | `/api/market/strategy-scan` | 策略选股 |
| 市场 | GET | `/api/market/tactics` | 实战形态技巧清单 |
| 市场 | POST | `/api/market/tactic-scan` | 实战形态扫描（六条可复核技巧） |
| 市场 | GET | `/api/market/tactic-check` | 单票实战形态逐条体检 |
| 市场 | GET | `/api/market/daily-recommend` | 每日收盘推荐 |
| 市场 | GET | `/api/market/prediction` | 明日大盘推衍 |
| 市场 | GET | `/api/market/winrate` | 胜率看板 |
| 市场 | GET | `/api/market/opportunity/auction` | 早盘竞价机会 |
| 市场 | GET | `/api/market/opportunity/closing` | 尾盘机会 |
| 简报 | GET | `/api/briefing/today` | 今日作战简报 |
| 回测 | POST | `/api/backtest/run` | 运行策略回测 |
| 回测 | POST | `/api/backtest/tactic` | 实战形态回测验证（walk-forward + 基准对比） |
| 市场 | GET | `/api/market/tactic-evidence` | 形态证据等级总览（分级口径 + 覆盖计数 + 证据快照） |
| 市场 | GET | `/api/market/spot-status` | 行情源冷却状态（强制刷新前判断） |
| 持仓 | GET / POST | `/api/portfolio/holdings` | 持仓 CRUD |
| 持仓 | GET | `/api/portfolio/advice` | 持仓建议 |
| 模拟盘 | POST | `/api/sim/trade` | 模拟买卖 |
| 模拟盘 | GET | `/api/sim/performance` | 净值曲线 + 胜率统计 |
| 自选 | GET / POST | `/api/watchlist` | 自选股增删 / 批量导入 |
| 预警 | GET / POST | `/api/alerts/rules` | 预警规则管理 |
| 预警 | GET | `/api/alerts/events` | 预警事件列表 |
| 预警 | GET | `/api/alerts/unread` | 未读角标 |
| 榜单 | GET | `/api/market/quad` | 榜单 |
| 历史 | GET | `/api/history/batches` | 分析历史批次 |
| 认证 | POST | `/api/auth/signin` | 登录 |
| 定时 | POST | `/api/cron/daily` | 每日结算（Vercel Cron 触发） |

---

## 🐳 Docker 部署

```bash
cp .env.example .env   # 填写 DEEPSEEK_API_KEY / SUPABASE_* / ALLOWED_ORIGINS
docker compose up -d --build
```

生产环境注意：设置 `ALLOWED_ORIGINS` 为前端域名（勿留空）；开启 `ENABLE_RATE_LIMIT=true`；经 HTTPS 反向代理（Nginx / Caddy）对外。

## ☁️ Vercel 部署

前后端分离部署：

```bash
cd backend && vercel --prod     # 入口 api/index.py，maxDuration 60
cd frontend && vercel --prod    # vercel.json 将 /api/* 代理到后端
```

- CORS：生产环境使用精确前端域名白名单；新增域名时通过 `ALLOWED_ORIGINS` 显式配置。Supabase 持久化按上文配置。
- SQLite 在 Serverless 只读文件系统落到 `/tmp`，冷启动后历史记录丢失——生产请用 Supabase。

---

## 🗺️ 路线图

详见 [ROADMAP.md](./ROADMAP.md)。**V6 预警中心（站内提醒）已落地**（规则引擎 / 事件去重 / 未读角标 / 盘中外部调度），当前重点是把「唯一收益为正的口径」做实与盘中链路体验收敛；后续规划 V6.5 外部推送、V7 组合分析与风控、V8 复盘社交化、V9 AI 增强、V10 实时行情。

历史变更见 [CHANGELOG.md](./CHANGELOG.md)。

## ⚠️ 免责声明

- 数据来自 akshare（腾讯 / 新浪行情、东方财富新闻等），受接口稳定性与合规影响，已加缓存与降级路径。
- LLM / 规则分析、推荐、信号、模拟盘结果**仅供参考，不构成任何投资建议**；信号标注「算法推导」，风险自负。
- 本项目用于学习与量化研究，实盘请谨慎。
