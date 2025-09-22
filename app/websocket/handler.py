# app/websocket/handler.py (更新版本，集成RAG功能)
from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import json
import redis.asyncio as redis

from ..database import AsyncSessionLocal
from ..models import Character, Conversation, Message
from ..services.llm_service import LLMService
from ..services.stt_service import stt_service
from ..services.tts_service import tts_service
from ..services.storage_service import storage_service
from ..config import settings


class ConnectionManager:
    def __init__(self):
        self.active_connections: dict = {}
        self.redis_client = None

    async def connect(self, websocket: WebSocket, session_id: str):
        await websocket.accept()
        self.active_connections[session_id] = websocket

        if not self.redis_client:
            self.redis_client = await redis.from_url(settings.REDIS_URL)

    def disconnect(self, session_id: str):
        if session_id in self.active_connections:
            del self.active_connections[session_id]

    async def send_message(self, message: dict, session_id: str):
        if session_id in self.active_connections:
            websocket = self.active_connections[session_id]
            await websocket.send_json(message)


manager = ConnectionManager()


async def handle_websocket(
        websocket: WebSocket,
        session_id: str,
        conversation_id: int
):
    await manager.connect(websocket, session_id)

    try:
        async with AsyncSessionLocal() as db:
            # 获取对话和角色信息
            result = await db.execute(
                select(Conversation).where(Conversation.id == conversation_id)
            )
            conversation = result.scalar_one_or_none()

            if not conversation:
                await websocket.send_json({"error": "Conversation not found"})
                return

            result = await db.execute(
                select(Character).where(Character.id == conversation.character_id)
            )
            character = result.scalar_one_or_none()

            # 获取历史消息（最近10条）
            result = await db.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at.desc())
                .limit(10)
            )
            recent_messages = result.scalars().all()
            recent_messages.reverse()

            # 构建消息历史
            message_history = [
                {"role": msg.role, "content": msg.content}
                for msg in recent_messages
            ]

            while True:
                data = await websocket.receive_json()
                message_type = data.get("type")

                if message_type == "text":
                    # 文字消息
                    user_content = data.get("content")

                    # 保存用户消息
                    user_message = Message(
                        conversation_id=conversation_id,
                        role="user",
                        content=user_content
                    )
                    db.add(user_message)
                    await db.commit()

                    # 添加到历史
                    message_history.append({"role": "user", "content": user_content})

                    # 生成AI回复（支持RAG）
                    ai_content = ""
                    async for chunk in LLMService.generate_response(
                            messages=message_history[-10:],  # 只使用最近10条
                            character_prompt=character.prompt_template,
                            character_id=character.id if character.use_rag else None,  # 根据设置决定是否使用RAG
                            use_rag=character.use_rag
                    ):
                        ai_content += chunk
                        await manager.send_message({
                            "type": "text_stream",
                            "content": chunk
                        }, session_id)

                    # 保存AI消息
                    ai_message = Message(
                        conversation_id=conversation_id,
                        role="assistant",
                        content=ai_content
                    )
                    db.add(ai_message)
                    await db.commit()

                    # 生成语音
                    if data.get("need_audio", False):
                        audio_data = await tts_service.synthesize(
                            ai_content,
                            character.voice_id
                        )
                        audio_url = await storage_service.upload_audio(audio_data)

                        ai_message.audio_url = audio_url
                        await db.commit()

                        await manager.send_message({
                            "type": "audio",
                            "url": audio_url
                        }, session_id)

                    message_history.append({"role": "assistant", "content": ai_content})

                elif message_type == "audio":
                    # 音频消息
                    audio_data = data.get("data")  # Base64编码的音频数据

                    # 语音识别
                    import base64
                    audio_bytes = base64.b64decode(audio_data)
                    user_content = await stt_service.transcribe(audio_bytes)

                    await manager.send_message({
                        "type": "transcription",
                        "content": user_content
                    }, session_id)

                    # 保存用户消息
                    user_message = Message(
                        conversation_id=conversation_id,
                        role="user",
                        content=user_content
                    )
                    db.add(user_message)
                    await db.commit()

                    # 添加到历史
                    message_history.append({"role": "user", "content": user_content})

                    # 生成AI回复（支持RAG）
                    ai_content = ""
                    async for chunk in LLMService.generate_response(
                            messages=message_history[-10:],  # 只使用最近10条
                            character_prompt=character.prompt_template,
                            character_id=character.id if character.use_rag else None,  # 根据设置决定是否使用RAG
                            use_rag=character.use_rag
                    ):
                        ai_content += chunk
                        await manager.send_message({
                            "type": "text_stream",
                            "content": chunk
                        }, session_id)

                    # 保存AI消息
                    ai_message = Message(
                        conversation_id=conversation_id,
                        role="assistant",
                        content=ai_content
                    )
                    db.add(ai_message)
                    await db.commit()

                    # 生成语音
                    if data.get("need_audio", False):
                        audio_data = await tts_service.synthesize(
                            ai_content,
                            character.voice_id
                        )
                        audio_url = await storage_service.upload_audio(audio_data)

                        ai_message.audio_url = audio_url
                        await db.commit()

                        await manager.send_message({
                            "type": "audio",
                            "url": audio_url
                        }, session_id)

                    message_history.append({"role": "assistant", "content": ai_content})


    except WebSocketDisconnect:
        manager.disconnect(session_id)
    except Exception as e:
        await websocket.send_json({"error": str(e)})
        manager.disconnect(session_id)