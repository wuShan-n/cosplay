from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    # 基础配置
    APP_NAME: str = "AI Roleplay API"
    DEBUG: bool = False
    API_PREFIX: str = "/api/v1"
    SECRET_KEY: str

    # 数据库
    DATABASE_URL: str
    REDIS_URL: str = "redis://localhost:6379"

    # 通义千问
    DASHSCOPE_API_KEY: str

    # 七牛云
    QINIU_ACCESS_KEY: str
    QINIU_SECRET_KEY: str
    QINIU_BUCKET: str
    QINIU_DOMAIN: str

    # Whisper配置
    WHISPER_MODEL: str = "base"
    WHISPER_DEVICE: str = "cpu"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

settings = Settings()