# AI 选股分析工具

LLM 驱动的 A 股选股分析平台：输入股票代码，AI 结合实时行情、K 线趋势与最新新闻，输出基本面/技术面/资金面/消息面综合评分与操作建议。支持行业板块查看、全市场条件扫描选股、分析历史记录。

## 功能特性

- **AI 选股分析**：SSE 流式输出分析过程，四维评分（基本面/技术面/资金面/消息面）+ 风险提示 + 操作建议
- **双模式**：配置 DeepSeek API Key 用 LLM 深度分析；未配置自动降级为本地规则评分
- **市场扫描**：49 个行业板块列表 + 全市场条件扫描（价格/涨幅/成交额过滤），勾选后一键送入分析
- **历史记录**：SQLite 持久化保存每次分析批次，随时回看详情
- **部署就绪**：CORS 白名单配置、接口限流中间件、Dockerfile + docker-compose

## 技术栈

- **后端**：Python 3.11 · FastAPI · akshare（A股数据）· DeepSeek API · SQLite
- **前端**：React 18 · Vite · TypeScript · Tailwind CSS · ECharts
- **交互**：REST + SSE 流式分析进度

## 快速开始

### 1. 启动后端

```bash
cd backend
pip install -r requirements.txt

# 配置 API Key（可选：不配置则使用本地规则评分）
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY 即启用 LLM 深度分析

# 启动（http://localhost:8000）
python -m app.main
```

### 2. 启动前端

```bash
cd frontend
npm install
npm run dev
```

浏览器打开 http://localhost:5173 。

## 项目结构

```
ai-stock-picker/
├── backend/
│   ├── app/
│   │   ├── main.py               # FastAPI 入口（CORS/限流/健康检查）
│   │   ├── config.py             # 配置（.env）
│   │   ├── models.py             # 数据模型
│   │   ├── store.py              # SQLite 历史记录存储
│   │   ├── services/
│   │   │   ├── data_service.py   # 数据获取（腾讯行情/K线 + 新闻）
│   │   │   └── llm_service.py    # DeepSeek 流式分析 + 规则评分兜底
│   │   └── routes/
│   │       ├── stock.py          # 行情/K线/新闻接口
│   │       ├── analysis.py       # 选股分析 SSE 接口
│   │       ├── market.py         # 行业板块/全市场扫描接口
│   │       └── history.py        # 历史记录接口
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   └── src/
│       ├── App.tsx               # 主页面（Tab: 选股/扫描/历史）
│       ├── api/client.ts         # API + SSE 客户端
│       ├── components/
│       │   ├── StockCard.tsx     # 个股分析卡片
│       │   ├── KLineChart.tsx    # ECharts K线图
│       │   ├── ScoreBar.tsx      # 维度评分条
│       │   ├── MarketPanel.tsx   # 板块列表 + 扫描选股
│       │   └── HistoryPanel.tsx  # 历史记录列表 + 详情
│       └── types.ts
├── Dockerfile                    # 后端镜像
└── docker-compose.yml            # 一键部署
```

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查（含当前模式） |
| GET | `/api/stock/{code}` | 个股行情 + K线 |
| GET | `/api/stock/{code}/news` | 个股新闻 |
| POST | `/api/analysis/stocks` | 批量选股分析（SSE 流式） |
| GET | `/api/market/industries` | 行业板块列表 |
| GET | `/api/market/industries/{label}/stocks` | 板块成分股 |
| POST | `/api/market/scan` | 全市场扫描选股 |
| GET | `/api/history/batches` | 历史批次列表 |
| GET | `/api/history/batches/{id}` | 批次详情 |

## 配置说明（backend/.env）

| 变量 | 说明 |
|------|------|
| `DEEPSEEK_API_KEY` | DeepSeek Key，留空则本地规则评分 |
| `LLM_MODE` | `auto`（默认）/ `mock`（强制规则）/ `real`（强制 LLM） |
| `ALLOWED_ORIGINS` | 生产环境 CORS 白名单，逗号分隔 |
| `ENABLE_RATE_LIMIT` | 是否开启接口限流（`true`/`false`） |

## Docker 部署

```bash
cp .env.example .env   # 填写 DEEPSEEK_API_KEY 和 ALLOWED_ORIGINS
docker compose up -d --build
```

生产环境注意：
- 设置 `ALLOWED_ORIGINS` 为你的前端域名（不要留空）
- 开启 `ENABLE_RATE_LIMIT=true`
- 通过 HTTPS 反向代理（Nginx/Caddy）对外提供服务

## Vercel 部署

本项目已适配 Vercel Serverless，前后端分离部署：

### 后端（`backend/` 目录）

```bash
cd backend
vercel --prod
```

- 入口：`api/index.py`（ASGI），`vercel.json` 配置 `maxDuration: 60`
- CORS：Vercel 环境自动放行 `*.vercel.app` 域名，无需额外配置
- SQLite：Serverless 文件系统只读，数据库落到 `/tmp`（冷启动后历史记录丢失，后续接入 Supabase 持久化）

### 前端（`frontend/` 目录）

```bash
cd frontend
vercel --prod
```

- `vercel.json` 将 `/api/*` rewrites 代理到后端，前端使用相对路径，避免跨域
- 如前后端分离部署且不用代理，可在项目设置环境变量 `VITE_API_BASE` 指向后端域名
- 部署后在后端项目配置 `DEEPSEEK_API_KEY` 环境变量即可启用 LLM 深度分析

> 注意：Windows PowerShell 下用 `vercel env add` 传值时可能带入 BOM 字符，建议在 Vercel 控制台页面配置环境变量。

## 说明

- 数据来自 akshare（腾讯/新浪行情，东方财富新闻），可能受接口稳定性影响
- 全市场扫描首次约 20 秒（已加 5 分钟缓存）
- LLM 分析结果仅供参考，不构成投资建议
