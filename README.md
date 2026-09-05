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
- **技术信号**：压力位 / 支撑位 / 买入点 / 卖出点 / 止损位 / 风险收益比 / 信号强度
- **明日大盘推衍**：上证指数技术信号 + LLM 次日走势预测，卡片内嵌指数走势图

### 数据闭环 & 验证
- **每日收盘推荐**：策略候选 + LLM 精选 10 只（含推荐理由 / 置信分），按交易日缓存
- **胜率看板**：预测命中率 + 推荐次日胜率
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

1. 在 Supabase 新建项目，按顺序执行 `backend/supabase-schema.sql`（v1）及 `supabase-schema-v2.sql` … `supabase-schema-v6.sql`；
   或部署后端后调用 `POST /api/admin/migrate` 自动执行全部迁移（需先配置 `ADMIN_TOKEN` 与 `SUPABASE_MANAGEMENT_API_KEY`）。
   所有脚本均幂等，可重复执行。
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

## 📁 项目结构

```
ai-stock-picker/
├── backend/
│   ├── app/
│   │   ├── main.py               # FastAPI 入口（CORS/限流/健康检查/路由注册）
│   │   ├── config.py             # pydantic-settings 配置
│   │   ├── models.py             # 数据模型
│   │   ├── store.py              # SQLite 本地分析历史
│   │   ├── routes/               # 14 个路由模块（见下）
│   │   └── services/            # 18 个服务模块（见下）
│   ├── supabase-schema*.sql      # 建表脚本 v1–v6（幂等，可重复执行）
│   ├── requirements.txt
│   └── vercel.json
├── frontend/
│   └── src/
│       ├── App.tsx              # 4 Tab 主框架：发现好股 / 选股扫描 / 深度分析 / 我的
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
`stock`（行情 / K 线 / 新闻）· `analysis`（选股分析 SSE）· `market`（板块 / 扫描 / 推荐 / 大盘推衍 / 机会）· `history`（历史批次）· `auth`（登录注册）· `cron`（每日结算 / 扫描）· `alerts`（预警中心）· `backtest`（回测）· `portfolio`（持仓）· `sim`（模拟盘）· `watchlist`（自选股）· `briefing`（今日简报）· `quad`（榜单）· `monitor`（监控）

**后端服务**（`app/services`）：
`data_service`（akshare 行情 / 新闻）· `llm_service`（DeepSeek + 规则兜底）· `signal_service`（技术信号）· `market_prediction`（大盘推衍）· `recommend_service`（每日推荐）· `backtest_service` · `portfolio_service` · `sim_service`（交易引擎）· `watchlist_service` · `alert_service` · `winrate_service`（胜率）· `trade_calendar_service`（交易日历）· `opportunity_service`（盘前 / 尾盘机会）· `quad_service` · `briefing_service` · `import_service`（持仓截图 / 文本导入）· `supabase_store`（Supabase 持久化）

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
| 市场 | GET | `/api/market/daily-recommend` | 每日收盘推荐 |
| 市场 | GET | `/api/market/prediction` | 明日大盘推衍 |
| 市场 | GET | `/api/market/winrate` | 胜率看板 |
| 市场 | GET | `/api/market/opportunity/auction` | 早盘竞价机会 |
| 市场 | GET | `/api/market/opportunity/closing` | 尾盘机会 |
| 简报 | GET | `/api/briefing/today` | 今日作战简报 |
| 回测 | POST | `/api/backtest/run` | 运行策略回测 |
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

- CORS：Vercel 环境自动放行 `*.vercel.app`；Supabase 持久化按上文配置。
- SQLite 在 Serverless 只读文件系统落到 `/tmp`，冷启动后历史记录丢失——生产请用 Supabase。

---

## 🗺️ 路线图

详见 [ROADMAP.md](./ROADMAP.md)。当前重点：V6 预警中心（站内提醒）落地中；后续规划 V6.5 外部推送、V7 组合分析与风控、V8 复盘社交化、V9 AI 增强、V10 实时行情。

历史变更见 [CHANGELOG.md](./CHANGELOG.md)。

## ⚠️ 免责声明

- 数据来自 akshare（腾讯 / 新浪行情、东方财富新闻等），受接口稳定性与合规影响，已加缓存与降级路径。
- LLM / 规则分析、推荐、信号、模拟盘结果**仅供参考，不构成任何投资建议**；信号标注「算法推导」，风险自负。
- 本项目用于学习与量化研究，实盘请谨慎。
