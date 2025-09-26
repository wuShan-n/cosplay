from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import uuid
from fastapi import FastAPI
import logging
from logging.handlers import RotatingFileHandler
from .config import settings
from .database import engine, Base
from .api import auth, characters, chat, knowledge
from .websocket.handler import handle_websocket
from fastapi.responses import FileResponse
import os
os.environ['KMP_DUPLICATE_LIB_OK'] = 'TRUE'
@asynccontextmanager
async def lifespan(app: FastAPI):
    #日志排查使用
    setup_logging()
    # 启动时创建数据库表
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # 关闭时的清理工作

app = FastAPI(
    title=settings.APP_NAME,
    lifespan=lifespan
)


def setup_logging():
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # 设置根日志记录器
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    )
    db_logger = logging.getLogger('sqlalchemy.engine')
    db_logger.setLevel(logging.INFO)  # 设置为INFO以记录所有SQL语句
# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应该设置具体的域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(auth.router, prefix=settings.API_PREFIX)
app.include_router(characters.router, prefix=settings.API_PREFIX)
app.include_router(chat.router, prefix=settings.API_PREFIX)
app.include_router(knowledge.router, prefix=settings.API_PREFIX)

# @app.get("/")
# async def root():
#     return {"message": "AI Roleplay API with RAG is running"}

@app.get("/")
async def root():
    # 指定wb.html文件的绝对路径
    wb_path = r"./doc/wb.html"
    return FileResponse(wb_path)
@app.websocket("/ws/{conversation_id}")
async def websocket_endpoint(websocket: WebSocket, conversation_id: int):
    session_id = str(uuid.uuid4())
    await handle_websocket(websocket, session_id, conversation_id)

# 健康检查
@app.get("/health")
async def health_check():
    return {"status": "healthy"}