from functools import lru_cache

from pydantic_settings import BaseSettings


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
    # SQLite 数据库路径
    database_path: str = "data/app.db"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
