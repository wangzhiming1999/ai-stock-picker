"""运维管理接口（需 ADMIN_TOKEN）：自动执行数据库迁移，免去手动 SQL Editor。

执行 SQL 支持两种方式（按优先级）：
  1) SUPABASE_MANAGEMENT_API_KEY：调用 Supabase Management API 的 database/query，
     只需一个 Key，无需暴露 DB 密码（推荐）。
  2) DATABASE_URL：直连 Postgres 跑 SQL（asyncpg）。

所有建表文件均使用 IF NOT EXISTS / ADD COLUMN IF NOT EXISTS，可重复执行幂等。
"""
from __future__ import annotations

import glob
import re
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from app.config import get_settings

router = APIRouter(prefix="/api/admin", tags=["admin"])

# backend/ 目录（admin.py 位于 backend/app/routes/）
BACKEND_DIR = Path(__file__).resolve().parents[2]

# 预期应存在的表（用于 status 自检）
EXPECTED_TABLES = [
    "user_profiles",
    "portfolio_holdings",
    "watchlist",
    "analysis_batches",
    "analysis_results",
    "daily_recommendations",
    "winrate_snapshot",
    "alert_rules",
    "alert_events",
    "sim_trades",
    "portfolio_snapshots",
    "market_spot_cache",
]


def _require_admin(x_admin_token: str | None = Header(None, alias="X-Admin-Token"), authorization: str | None = Header(None)):
    """ADMIN_TOKEN 鉴权；未配置则禁用本组接口。"""
    s = get_settings()
    if not s.admin_token:
        raise HTTPException(status_code=403, detail="未配置 ADMIN_TOKEN，迁移接口已禁用")
    provided = x_admin_token
    if not provided and authorization and authorization.lower().startswith("bearer "):
        provided = authorization.split(" ", 1)[1].strip()
    if provided != s.admin_token:
        raise HTTPException(status_code=401, detail="管理员令牌无效")
    return True


def _ordered_schema_files():
    """返回 [(版本标签, Path)]，按 v1 → vN 排序。"""
    files: list[tuple[str, Path]] = []
    base = BACKEND_DIR / "supabase-schema.sql"
    if base.exists():
        files.append(("v1", base))
    for p in sorted(glob.glob(str(BACKEND_DIR / "supabase-schema-v*.sql"))):
        m = re.search(r"supabase-schema-v(\d+)\.sql$", p)
        ver = int(m.group(1)) if m else 0
        files.append((f"v{ver}", Path(p)))
    return files


async def _run_sql(sql: str) -> dict:
    """执行一段 SQL，返回解析后的结果（Management API 优先，DATABASE_URL 兜底）。"""
    s = get_settings()
    if s.supabase_management_api_key:
        ref = _project_ref(s.supabase_url)
        if not ref:
            raise HTTPException(status_code=400, detail="无法从 supabase_url 解析 project ref")
        import httpx

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"https://api.supabase.com/v1/projects/{ref}/database/query",
                headers={"Authorization": f"Bearer {s.supabase_management_api_key}", "Content-Type": "application/json"},
                json={"query": sql},
            )
        if resp.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"Management API 执行失败 {resp.status_code}: {resp.text[:400]}")
        try:
            return resp.json()
        except Exception:
            return {"raw": resp.text[:200]}
    if s.database_url:
        import asyncpg

        conn = await asyncpg.connect(s.database_url)
        try:
            await conn.execute(sql)
            return {"executed": True}
        finally:
            await conn.close()
    raise HTTPException(
        status_code=400,
        detail="未配置 SUPABASE_MANAGEMENT_API_KEY 或 DATABASE_URL，无法自动执行迁移。"
        "请在 Vercel 环境变量中配置其一后重试。",
    )


def _project_ref(supabase_url: str) -> str | None:
    m = re.search(r"https://([^.]+)\.supabase\.co", supabase_url or "")
    return m.group(1) if m else None


@router.get("/migrate/status")
async def migrate_status(_: bool = Depends(_require_admin)):
    """列出预期表的存在情况，确认缺哪些。"""
    try:
        rows = await _run_sql(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name;"
        )
    except HTTPException:
        return {"error": "无法连接执行自检，请检查 SUPABASE_MANAGEMENT_API_KEY / DATABASE_URL 配置"}
    existing = {r["table_name"] for r in rows} if isinstance(rows, list) else set()
    missing = [t for t in EXPECTED_TABLES if t not in existing]
    return {"existing": sorted(existing), "expected": EXPECTED_TABLES, "missing": missing, "all_ok": not missing}


@router.post("/migrate")
async def migrate(_: bool = Depends(_require_admin), only: str | None = Query(None, description="仅执行指定版本，如 v4 / v5")):
    """执行全部（或 only=指定版本）迁移 SQL。幂等，可重复执行。"""
    files = _ordered_schema_files()
    if only:
        files = [f for f in files if f[0] == only]
    if not files:
        return {"results": [], "success": True, "note": "无匹配迁移文件"}
    results = []
    for ver, path in files:
        sql = path.read_text(encoding="utf-8")
        try:
            await _run_sql(sql)
            results.append({"version": ver, "file": path.name, "status": "ok"})
        except HTTPException as e:
            results.append({"version": ver, "file": path.name, "status": "error", "detail": e.detail})
    failed = [r for r in results if r["status"] != "ok"]
    return {"results": results, "success": not failed, "failed": failed}
