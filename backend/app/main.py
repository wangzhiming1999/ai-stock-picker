import os
import time
from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import store
from app.config import get_settings
from app.routes import analysis, history, market, stock

settings = get_settings()


# ---------- 简单限流中间件（IP + 路径 滑动窗口） ----------
class RateLimiter:
    def __init__(self, max_requests: int = 60, window: int = 60):
        self.max_requests = max_requests
        self.window = window
        self.hits: dict[str, list[float]] = defaultdict(list)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        self.hits[key] = [t for t in self.hits[key] if now - t < self.window]
        if len(self.hits[key]) >= self.max_requests:
            return False
        self.hits[key].append(now)
        return True


_rate_limiter = RateLimiter()


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.init_db()
    yield


app = FastAPI(
    title="AI 选股分析工具",
    description="LLM 驱动的 A 股选股分析平台",
    version="0.2.0",
    lifespan=lifespan,
)

# ---------- CORS ----------
# 优先级：ALLOWED_ORIGINS 白名单 > Vercel 环境自动放行 *.vercel.app > 本地开发全放行
_cors_kwargs = {
    "allow_credentials": True,
    "allow_methods": ["*"],
    "allow_headers": ["*"],
}

if settings.allowed_origins:
    _cors_kwargs["allow_origins"] = [o.strip() for o in settings.allowed_origins.split(",") if o.strip()]
elif os.getenv("VERCEL"):
    # 部署在 Vercel 但未显式配置白名单时，放行所有 Vercel 部署域名（含预览环境）
    _cors_kwargs["allow_origin_regex"] = r"https://[a-zA-Z0-9-]+\.vercel\.app"
else:
    # 本地开发
    _cors_kwargs["allow_origins"] = ["*"]

app.add_middleware(CORSMiddleware, **_cors_kwargs)


# ---------- 限流中间件 ----------
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if settings.enable_rate_limit:
        key = f"{request.client.host}:{request.url.path}"
        if not _rate_limiter.allow(key):
            return JSONResponse(status_code=429, content={"detail": "请求过于频繁，请稍后再试"})
    return await call_next(request)


app.include_router(stock.router)
app.include_router(analysis.router)
app.include_router(market.router)
app.include_router(history.router)


@app.get("/api/health")
async def health():
    from app.services.llm_service import should_use_mock

    return {
        "status": "ok",
        "model": settings.deepseek_model,
        "api_configured": bool(settings.deepseek_api_key),
        "mode": "mock(本地规则)" if should_use_mock() else "llm(DeepSeek)",
        "rate_limit": settings.enable_rate_limit,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.backend_host, port=settings.backend_port, reload=True)
