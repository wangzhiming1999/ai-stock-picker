import os
import threading
import time
from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.responses import Response

from app import store
from app.config import get_settings
from app.routes import analysis, alerts, auth, backtest, briefing, cron, history, market, monitor, portfolio, quad, sim, stock, watchlist, admin

settings = get_settings()

_PRODUCTION_FRONTEND_ORIGINS = [
    "https://frontend-vert-kappa-64.vercel.app",
    "https://frontend-wnagzhimings-projects.vercel.app",
]


def _effective_rate_limit(configured: bool, is_vercel: bool) -> bool:
    return configured or is_vercel


def _resolve_cors_origins(configured: str, is_vercel: bool) -> list[str]:
    if configured:
        return [origin.strip() for origin in configured.split(",") if origin.strip()]
    if is_vercel:
        return list(_PRODUCTION_FRONTEND_ORIGINS)
    return ["*"]


def _apply_security_headers(response: Response, is_vercel: bool) -> None:
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if is_vercel:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"


_is_vercel = bool(os.getenv("VERCEL"))
_rate_limit_enabled = _effective_rate_limit(settings.enable_rate_limit, _is_vercel)


# ---------- 简单限流中间件（IP + 路径 滑动窗口） ----------
class RateLimiter:
    def __init__(self, max_requests: int = 60, window: int = 60, max_keys: int = 10_000):
        self.max_requests = max_requests
        self.window = window
        self.max_keys = max_keys
        self.hits: dict[str, list[float]] = defaultdict(list)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        timestamps = [t for t in self.hits.get(key, []) if now - t < self.window]
        if len(timestamps) >= self.max_requests:
            self.hits[key] = timestamps
            return False
        timestamps.append(now)
        self.hits[key] = timestamps
        if len(self.hits) > self.max_keys:
            stale = [k for k, values in self.hits.items() if not values or now - values[-1] >= self.window]
            excess = max(1, len(self.hits) - self.max_keys)
            if len(stale) < excess:
                active = sorted(
                    ((k, values[-1]) for k, values in self.hits.items() if k not in stale and values),
                    key=lambda item: item[1],
                )
                stale.extend(k for k, _ in active[: excess - len(stale)])
            for stale_key in stale[:excess]:
                self.hits.pop(stale_key, None)
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
    "allow_origins": _resolve_cors_origins(settings.allowed_origins, _is_vercel),
    "allow_credentials": True,
    "allow_methods": ["*"],
    "allow_headers": ["*"],
}

app.add_middleware(CORSMiddleware, **_cors_kwargs)


# ---------- 限流中间件 ----------
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if _rate_limit_enabled:
        key = f"{request.client.host}:{request.url.path}"
        if not _rate_limiter.allow(key):
            return JSONResponse(status_code=429, content={"detail": "请求过于频繁，请稍后再试"})
    return await call_next(request)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    _apply_security_headers(response, _is_vercel)
    return response


app.include_router(stock.router)
app.include_router(analysis.router)
app.include_router(market.router)
app.include_router(history.router)
app.include_router(auth.router)
app.include_router(cron.router)
app.include_router(alerts.router)
app.include_router(backtest.router)
app.include_router(portfolio.router)
app.include_router(sim.router)
app.include_router(watchlist.router)
app.include_router(briefing.router)
app.include_router(quad.router)
app.include_router(monitor.router)
app.include_router(admin.router)


@app.get("/api/health")
async def health():
    from app.services.llm_service import should_use_mock

    from app.services.supabase_store import is_configured as supabase_configured

    # 暴露 LLM 端点域名（去敏），便于核对 model 与 base_url 是否匹配：
    # base=api.deepseek.com 时 model 必须是 deepseek-chat / deepseek-reasoner，
    # 若填 deepseek-ai/DeepSeek-V3（硅基流动命名）会因模型不存在而调用失败降级。
    base = (settings.deepseek_base_url or "").strip()
    host = base.split("://", 1)[1].split("/")[0] if "://" in base else ""

    return {
        "status": "ok",
        "model": settings.deepseek_model,
        "llm_host": host or None,
        "api_configured": bool(settings.deepseek_api_key),
        "mode": "mock(本地规则)" if should_use_mock() else "llm(DeepSeek)",
        "rate_limit": _rate_limit_enabled,
        "supabase": supabase_configured(),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.backend_host, port=settings.backend_port, reload=True)
