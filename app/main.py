from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import uuid

from .config import settings
from .database import engine, Base
from .api import auth, characters, chat, knowledge
from .websocket.handler import handle_websocket

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时创建数据库表
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # 关闭时的清理工作

app = FastAPI(
    title=settings.APP_NAME,
    lifespan=lifespan
)

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

@app.get("/")
async def root():
    return {"message": "AI Roleplay API with RAG is running"}

@app.websocket("/ws/{conversation_id}")
async def websocket_endpoint(websocket: WebSocket, conversation_id: int):
    session_id = str(uuid.uuid4())
    await handle_websocket(websocket, session_id, conversation_id)

# 健康检查
@app.get("/health")
async def health_check():
    return {"status": "healthy"}