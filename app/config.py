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

    # 通义千问
    DASHSCOPE_API_KEY: str

    # 七牛云
    QINIU_ACCESS_KEY: str
    QINIU_SECRET_KEY: str
    QINIU_BUCKET: str
    QINIU_DOMAIN: str

    # Whisper配置
    WHISPER_MODEL: str = "base"
    WHISPER_DEVICE: str = "cuda"

    # IndexTTS2配置（新增）
    INDEXTTS2_API_URL: str = "http://localhost:6006"  # IndexTTS2 API地址
    DEFAULT_TTS_ENGINE: str = "edge_tts"  # 默认TTS引擎

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

settings = Settings()