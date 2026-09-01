import os
from functools import lru_cache

from pydantic_settings import BaseSettings


def _default_db_path() -> str:
    """Serverless 环境（Vercel/Railway 等）文件系统多为只读，数据库落到 /tmp。

    注意：/tmp 不持久化，冷启动后历史记录会丢失。
    需要持久化时请接入 Supabase/Postgres，或直接配置 DATABASE_PATH 到可写卷。
    """
    if os.getenv("VERCEL") or os.getenv("_HANDLER"):
        return "/tmp/app.db"
    return "data/app.db"


class Settings(BaseSettings):
    """应用配置，支持通过环境变量或 .env 覆盖"""

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    # auto: 有 API Key 用真实 LLM，否则用本地规则评分；也可显式设 mock / real
    llm_mode: str = "auto"

    backend_host: str = "0.0.0.0"
    backend_port: int = 8000

    # 生产环境 CORS 白名单（逗号分隔），空则允许所有
    allowed_origins: str = ""
    # 是否开启接口限流
    enable_rate_limit: bool = False
    # SQLite 数据库路径（未配置 Supabase 时使用）
    database_path: str = _default_db_path()

    # Supabase 配置（配置后历史记录/登录走 Supabase）
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_key: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
