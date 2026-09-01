"""Supabase 存储 + Auth 服务。

配置了 SUPABASE_URL / SERVICE_KEY 后，历史记录持久化到 Supabase Postgres，
登录注册通过 Supabase Auth 实现。
"""
from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

_client: Any | None = None
_service_client: Any | None = None


def is_configured() -> bool:
    s = get_settings()
    return bool(s.supabase_url and s.supabase_service_key)


def get_service_client():
    """后端管理客户端（service_role key，绕过 RLS）。"""
    global _service_client
    if _service_client is None:
        from supabase import create_async_client

        s = get_settings()
        _service_client = create_async_client(s.supabase_url, s.supabase_service_key)
    return _service_client


def get_public_client():
    """公共客户端（anon key，用于 Auth 操作，遵循 RLS）。"""
    global _client
    if _client is None:
        from supabase import create_async_client

        s = get_settings()
        _client = create_async_client(s.supabase_url, s.supabase_anon_key)
    return _client


# ---------- Auth ----------

async def sign_up(email: str, password: str) -> dict:
    client = get_public_client()
    res = await client.auth.sign_up({"email": email, "password": password})
    user = getattr(res, "user", None)
    session = getattr(res, "session", None)
    if user is None:
        # 邮箱确认开启时 user 存在但 session 为空
        return {"user": user, "session": session}
    return {"user": user, "session": session}


async def sign_in(email: str, password: str) -> dict:
    client = get_public_client()
    res = await client.auth.sign_in_with_password({"email": email, "password": password})
    return {"user": res.user, "session": res.session}


async def get_user_by_token(token: str) -> dict | None:
    """通过 JWT 获取用户信息（用于接口鉴权）。"""
    try:
        res = await get_public_client().auth.get_user(token)
        return res.user
    except Exception as e:
        logger.debug("token 校验失败: %s", e)
        return None


# ---------- 历史记录（使用 service client 管理，关联 user_id） ----------

async def save_batch(user_id: str | None, codes: list[str], mode: str, results: list[dict]) -> int:
    """保存一批分析结果，返回 batch_id。"""
    sb = get_service_client()
    avg = round(sum(r["overall_score"] for r in results) / len(results), 2) if results else None
    batch_res = (
        await sb.table("analysis_batches")
        .insert(
            {
                "user_id": user_id,
                "codes": ",".join(codes),
                "mode": mode,
                "total": len(results),
                "avg_score": avg,
            }
        )
        .execute()
    )
    batch = batch_res.data[0]
    batch_id = batch["id"]

    rows = []
    for r in results:
        rows.append(
            {
                "batch_id": batch_id,
                "code": r["code"],
                "name": r["name"],
                "overall_score": r["overall_score"],
                "summary": r.get("summary", ""),
                "dimensions": r.get("dimensions", []),
                "risks": r.get("risks", []),
                "suggestions": r.get("suggestions", []),
            }
        )
    await sb.table("analysis_results").insert(rows).execute()
    return batch_id


async def list_batches(user_id: str | None, limit: int = 20) -> list[dict]:
    """列出最近的分析批次（只查当前用户的）。"""
    sb = get_service_client()
    query = sb.table("analysis_batches").select("*").order("created_at", desc=True).limit(limit)
    if user_id:
        query = query.eq("user_id", user_id)
    res = await query.execute()
    return res.data


async def get_batch(batch_id: int, user_id: str | None) -> dict | None:
    """查询批次及全部结果（校验归属）。"""
    sb = get_service_client()
    q = sb.table("analysis_batches").select("*").eq("id", batch_id)
    if user_id:
        q = q.eq("user_id", user_id)
    res = await q.execute()
    if not res.data:
        return None
    batch = res.data[0]
    results = await sb.table("analysis_results").select("*").eq("batch_id", batch_id).order("overall_score", desc=True).execute()
    batch["results"] = results.data
    return batch
