
import re
import base64
import logging
from datetime import datetime
from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..database import AsyncSessionLocal
from ..models import Character, Message
from ..services.llm_service import LLMService
from ..services.stt_service import stt_service
from ..services.tts_service import tts_service
from ..services.storage_service import storage_service
from ..services.rag_service import rag_service
from ..utils.query_utils import query_utils

logger = logging.getLogger(__name__)


class ConnectionManager:
    """WebSocket连接管理器"""

    def __init__(self):
        self.active_connections: dict = {}

    async def connect(self, websocket: WebSocket, session_id: str):
        await websocket.accept()
        self.active_connections[session_id] = websocket

    def disconnect(self, session_id: str):
        self.active_connections.pop(session_id, None)

    async def send_message(self, message: dict, session_id: str):
        if websocket := self.active_connections.get(session_id):
            await websocket.send_json(message)


manager = ConnectionManager()


class StreamProcessor:
    """简化的流式处理器"""

    # 句子结束标记
    SENTENCE_ENDS = re.compile(r'[。！？.!?]')
    # 最小有效文本长度
    MIN_TEXT_LENGTH = 2

    def __init__(self, session_id: str, character: Character):
        self.session_id = session_id
        self.character = character
        self.text_buffer = ""
        self.audio_chunks = []

    async def process_text_chunk(self, chunk: str) -> None:
        """处理文本块并生成音频"""
        # 1. 立即发送文本流
        await manager.send_message({
            "type": "text_stream",
            "content": chunk
        }, self.session_id)

        # 2. 添加到缓冲区
        self.text_buffer += chunk

        # 3. 检查是否有完整句子
        if match := self.SENTENCE_ENDS.search(self.text_buffer):
            sentence = self.text_buffer[:match.end()].strip()
            self.text_buffer = self.text_buffer[match.end():].lstrip()

            # 生成音频
            await self._synthesize_sentence(sentence)

    async def flush_buffer(self) -> None:
        """处理剩余的缓冲区内容"""
        if remaining := self.text_buffer.strip():
            await self._synthesize_sentence(remaining)
            self.text_buffer = ""

    async def _synthesize_sentence(self, text: str) -> None:
        """合成单个句子的音频"""
        if len(text) < self.MIN_TEXT_LENGTH:
            return

        try:
            async for audio_chunk in tts_service.synthesize_stream(
                    text=text,
                    voice_id=self.character.voice_id
            ):
                self.audio_chunks.append(audio_chunk)
                await manager.send_message({
                    "type": "audio_stream",
                    "data": base64.b64encode(audio_chunk).decode('utf-8')
                }, self.session_id)
        except Exception as e:
            logger.error(f"TTS合成失败: {e}")

    def get_full_audio(self) -> bytes:
        """获取完整的音频数据"""
        return b"".join(self.audio_chunks) if self.audio_chunks else b""


async def handle_websocket(
        websocket: WebSocket,
        session_id: str,
        conversation_id: int
):
    """处理WebSocket连接"""
    logger.info(f"WebSocket连接建立: session={session_id}, conversation={conversation_id}")
    await manager.connect(websocket, session_id)

    try:
        async with AsyncSessionLocal() as db:
            # 获取对话和角色信息
            conversation, character = await get_conversation_and_character(
                db, conversation_id
            )

            # 获取历史消息
            messages = await get_recent_messages(db, conversation_id)
            message_history = [
                {"role": msg.role, "content": msg.content}
                for msg in messages
            ]

            # 发送历史消息
            if messages:
                await send_history_messages(messages, session_id)

            # 消息处理循环
            while True:
                data = await websocket.receive_json()
                await process_message(
                    db, data, character, conversation_id,
                    message_history, session_id
                )

    except WebSocketDisconnect:
        logger.info(f"WebSocket断开: session={session_id}")
    except Exception as e:
        logger.error(f"WebSocket错误: {e}", exc_info=True)
        await manager.send_message({"error": "服务器错误"}, session_id)
    finally:
        manager.disconnect(session_id)


async def process_message(
        db: AsyncSession,
        data: dict,
        character: Character,
        conversation_id: int,
        message_history: list,
        session_id: str
):
    """处理单条消息"""
    message_type = data.get("type")

    if message_type == "load_history":
        await handle_load_history(db, data, conversation_id, session_id)
        return

    # 处理用户输入
    user_content = None
    user_audio_url = None

    if message_type == "text":
        user_content = data.get("content")
        await manager.send_message({
            "type": "transcription",
            "content": user_content,
            "is_corrected": True
        }, session_id)

    elif message_type == "audio":
        user_content, user_audio_url = await process_audio_input(
            data, session_id
        )

    if user_content:
        await generate_ai_response(
            db, character, conversation_id,
            user_content, user_audio_url,
            message_history, session_id
        )


async def generate_ai_response(
        db: AsyncSession,
        character: Character,
        conversation_id: int,
        user_content: str,
        user_audio_url: str,
        message_history: list,
        session_id: str
):
    """生成AI响应"""
    # RAG检索（如果启用）
    rag_context = ""
    if character.use_knowledge_base:
        chunks = await rag_service.search_knowledge(
            db, character.id, user_content,
            k=character.knowledge_search_k
        )
        if chunks:
            rag_context = await rag_service.build_context_prompt(chunks)

    # 保存用户消息
    user_message = Message(
        conversation_id=conversation_id,
        role="user",
        content=user_content,
        audio_url=user_audio_url
    )
    db.add(user_message)
    await db.commit()

    message_history.append({"role": "user", "content": user_content})

    # 构建增强提示词
    enhanced_prompt = character.prompt_template
    if rag_context:
        enhanced_prompt += f"\n\n相关知识:\n{rag_context}"

    # 流式生成响应
    processor = StreamProcessor(session_id, character)
    ai_content = ""

    async for chunk in LLMService.generate_response(
            messages=message_history,
            character_prompt=enhanced_prompt
    ):
        ai_content += chunk
        await processor.process_text_chunk(chunk)

    # 处理剩余内容
    await processor.flush_buffer()

    # 上传完整音频
    ai_audio_url = None
    if full_audio := processor.get_full_audio():
        try:
            ai_audio_url = await storage_service.upload_audio(full_audio)
            await manager.send_message({
                "type": "audio_complete",
                "url": ai_audio_url
            }, session_id)
        except Exception as e:
            logger.error(f"音频上传失败: {e}")

    # 保存AI消息
    ai_message = Message(
        conversation_id=conversation_id,
        role="assistant",
        content=ai_content,
        audio_url=ai_audio_url
    )
    db.add(ai_message)
    await db.commit()

    message_history.append({"role": "assistant", "content": ai_content})


# === 辅助函数 ===

async def get_conversation_and_character(
        db: AsyncSession,
        conversation_id: int
) -> tuple:
    """获取对话和角色信息"""
    conversation = await query_utils.get_conversation_with_character(
        db, conversation_id
    )
    if not conversation:
        raise ValueError("对话不存在")
    if not conversation.character:
        raise ValueError("角色不存在")
    return conversation, conversation.character


async def get_recent_messages(
        db: AsyncSession,
        conversation_id: int,
        limit: int = 10
) -> list:
    """获取最近的消息"""
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    messages = result.scalars().all()
    return list(reversed(messages))


async def send_history_messages(messages: list, session_id: str):
    """发送历史消息"""
    history_payload = [
        {
            "role": msg.role,
            "content": msg.content,
            "created_at": msg.created_at.isoformat(),
            "audio_url": msg.audio_url
        }
        for msg in messages
    ]
    await manager.send_message({
        "type": "history",
        "messages": history_payload
    }, session_id)


async def process_audio_input(data: dict, session_id: str) -> tuple:
    """处理音频输入"""
    audio_bytes = base64.b64decode(data.get("data"))

    # 语音识别
    user_content = await stt_service.transcribe_audio(audio_bytes)
    await manager.send_message({
        "type": "transcription",
        "content": user_content,
        "is_corrected": True
    }, session_id)

    # 上传音频
    user_audio_url = await storage_service.upload_audio(audio_bytes)
    if user_audio_url:
        await manager.send_message({
            "type": "audio",
            "url": user_audio_url
        }, session_id)

    return user_content, user_audio_url


async def handle_load_history(
        db: AsyncSession,
        data: dict,
        conversation_id: int,
        session_id: str
):
    """处理加载历史消息请求"""
    before_str = data.get("before_created_at")
    if not before_str:
        return

    try:
        before_dt = datetime.fromisoformat(
            before_str.replace("Z", "+00:00")
        )

        result = await db.execute(
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.created_at < before_dt
            )
            .order_by(Message.created_at.desc())
            .limit(20)
        )
        older_messages = list(reversed(result.scalars().all()))

        if older_messages:
            await send_history_messages(older_messages, session_id)

    except Exception as e:
        logger.error(f"加载历史消息失败: {e}")