from sqlalchemy import create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from .config import settings
import asyncio
import logging

# 配置日志
logger = logging.getLogger(__name__)

# 创建带连接池的异步引擎
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_size=20,           # 连接池大小
    max_overflow=10,        # 最大溢出连接数
    pool_recycle=1800,       # 连接回收时间（秒），设置为30分钟
    pool_timeout=30,        # 获取连接的超时时间（秒）
    pool_pre_ping=True,     # 关键设置：执行前检查连接是否有效
    connect_args={
        "server_settings": {
            "idle_in_transaction_session_timeout": "0",  # 禁用空闲事务超时
            "statement_timeout": "0"                      # 禁用语句超时
        }
    }
)

# 会话工厂
AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,        # 避免自动flush，提高性能
    future=True
)

Base = declarative_base()

async def get_db():
    """带重试机制和心跳检测的数据库会话"""
    session = AsyncSessionLocal()
    try:
        # 测试连接是否有效
        await session.execute(text("SELECT 1"))
        yield session
    except Exception as e:
        logger.error(f"数据库连接失败: {str(e)}")
        raise
    finally:
        await session.close()