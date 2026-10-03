"""Vercel Cron 与 FastAPI 路由契约测试。"""

from app.routes import cron


def _methods_for(path: str) -> set[str]:
    return {
        method
        for route in cron.router.routes
        if route.path == path
        for method in (route.methods or set())
    }


def test_vercel_scheduled_routes_accept_get_requests():
    """Vercel Cron 只发送 GET；配置中的路径必须接受 GET。"""
    assert "GET" in _methods_for("/api/cron/daily")
    assert "GET" in _methods_for("/api/cron/quad")


def test_manual_operations_can_still_use_post_requests():
    assert "POST" in _methods_for("/api/cron/daily")
    assert "POST" in _methods_for("/api/cron/quad")
