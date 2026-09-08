from starlette.responses import Response

from app.main import _apply_security_headers, _effective_rate_limit, _resolve_cors_origins


def test_rate_limit_is_always_enabled_on_vercel():
    assert _effective_rate_limit(configured=False, is_vercel=True) is True


def test_explicit_rate_limit_still_works_locally():
    assert _effective_rate_limit(configured=True, is_vercel=False) is True


def test_vercel_cors_fallback_is_exact_production_frontends():
    origins = _resolve_cors_origins("", is_vercel=True)

    assert "https://frontend-vert-kappa-64.vercel.app" in origins
    assert "https://attacker-preview.vercel.app" not in origins


def test_configured_cors_origins_override_defaults():
    assert _resolve_cors_origins("https://example.com, https://app.example.com", True) == [
        "https://example.com",
        "https://app.example.com",
    ]


def test_production_security_headers_are_applied():
    response = Response()
    _apply_security_headers(response, is_vercel=True)
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["strict-transport-security"].startswith("max-age=31536000")
