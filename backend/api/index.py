"""Vercel Serverless 入口（ASGI）。

Vercel Python runtime 会加载本模块的 `app` 变量（FastAPI ASGI 应用）。
依赖由 backend/requirements.txt 提供。
"""
import sys
from pathlib import Path

# 确保 backend 目录在模块搜索路径中（Vercel 以 backend/ 为项目根目录）
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main import app  # noqa: E402,F401
