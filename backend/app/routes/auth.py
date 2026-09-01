"""认证接口：注册、登录、当前用户。"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from app.services import supabase_store

router = APIRouter(prefix="/api/auth", tags=["auth"])


class AuthRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=72)


class TokenRequest(BaseModel):
    token: str


@router.post("/signup")
async def sign_up(req: AuthRequest):
    if not supabase_store.is_configured():
        raise HTTPException(status_code=503, detail="Supabase 未配置")
    try:
        res = await supabase_store.sign_up(req.email, req.password)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e).splitlines()[-1] if str(e) else "注册失败")
    return {"message": "注册成功，请查收邮箱确认" if not res.get("session") else "注册成功", **res}


@router.post("/signin")
async def sign_in(req: AuthRequest):
    if not supabase_store.is_configured():
        raise HTTPException(status_code=503, detail="Supabase 未配置")
    try:
        res = await supabase_store.sign_in(req.email, req.password)
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e).splitlines()[-1] if str(e) else "登录失败")
    session = res.get("session")
    if not session:
        raise HTTPException(status_code=401, detail="登录失败")
    return {
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "user": {"id": res["user"].id, "email": res["user"].email},
    }


@router.post("/user")
async def get_user(req: TokenRequest):
    user = await supabase_store.get_user_by_token(req.token)
    if user is None:
        raise HTTPException(status_code=401, detail="无效的 token")
    return {"id": user.id, "email": user.email}
