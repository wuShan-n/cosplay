from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import json
import redis.asyncio as redis
import base64
import logging
from ..services.context_agent import ContextAgent
from ..database import AsyncSessionLocal
from ..models import Character, Conversation, Message
from ..services.llm_service import LLMService
from ..services.stt_service import stt_service
from ..services.tts_service import tts_service
from ..services.storage_service import storage_service
from ..services.rag_service import rag_service
from ..services.text_correction_service import text_correction_service
from ..config import settings

# 配置日志记录器
logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self.active_connections: dict = {}

    async def connect(self, websocket: WebSocket, session_id: str):
        await websocket.accept()
        self.active_connections[session_id] = websocket

    def disconnect(self, session_id: str):
        if session_id in self.active_connections:
            del self.active_connections[session_id]

    async def send_message(self, message: dict, session_id: str):
        if session_id in self.active_connections:
            websocket = self.active_connections[session_id]
            await websocket.send_json(message)


manager = ConnectionManager()


async def get_conversation_and_character(db: AsyncSession, conversation_id: int, user_id: int = None):
    """
    获取对话和角色信息，并验证权限（如果提供了user_id）
    """
    # 获取对话
    conversation = await db.get(Conversation, conversation_id)
    if not conversation:
        raise ValueError("Conversation not found")

    # 获取角色
    character = await db.get(Character, conversation.character_id)
    if not character:
        raise ValueError("Character not found")

    return conversation, character


async def get_recent_messages(db: AsyncSession, conversation_id: int, limit: int = 10):
    """获取最近的消息"""
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    recent_messages = result.scalars().all()
    recent_messages.reverse()
    return recent_messages


async def generate_context_summary(messages: list) -> str:
    """
    使用Agent方式总结前10条消息，生成上下文提示
    包括情感分析、对话历史摘要和上下文提示
    """
    if not messages:
        return ""

    # 提取消息内容
    conversation_text = "\n".join([
        f"{msg.role}: {msg.content}" for msg in messages
    ])

    # 使用ContextAgent生成总结
    try:
        summary = await ContextAgent.generate_summary(conversation_text)
        # 截断到1000字符以内，确保符合数据库字段长度限制
        if len(summary) > 1000:
            summary = summary[:997] + "..."
        return summary
    except Exception as e:
        logger.error(f"生成上下文总结时出错: {e}")
        # 返回一个简单的摘要作为备选
        return f"对话历史摘要: 最近{len(messages)}条消息的对话上下文"


async def handle_websocket(
        websocket: WebSocket,
        session_id: str,
        conversation_id: int
):
    logger.info(f"WebSocket连接建立: session_id={session_id}, conversation_id={conversation_id}")
    await manager.connect(websocket, session_id)
    db = None
    try:
        async with AsyncSessionLocal() as db:
            # 获取对话和角色信息
            conversation, character = await get_conversation_and_character(db, conversation_id)
            logger.info(f"成功获取对话和角色信息: conversation_id={conversation_id}, character_id={character.id}")

            # 获取历史消息（最近10条）
            recent_messages = await get_recent_messages(db, conversation_id, 10)
            logger.debug(f"获取到 {len(recent_messages)} 条历史消息")

            # 构建消息历史
            message_history = [
                {"role": msg.role, "content": msg.content}
                for msg in recent_messages
            ]

            if recent_messages:

                history_payload = [
                    {
                        "role": msg.role,
                        "content": msg.content,
                        "created_at": msg.created_at.isoformat(),  # 发送时间戳有助于前端排序和显示
                        "audio_url": msg.audio_url
                    }
                    for msg in recent_messages
                ]
                await manager.send_message({
                    "type": "history",  # 定义一个清晰的消息类型
                    "messages": history_payload
                }, session_id)
                logger.info(f"已将 {len(history_payload)} 条历史消息发送到 session_id={session_id}")

            while True:
                data = await websocket.receive_json()
                message_type = data.get("type")
                need_audio = data.get("need_audio", False)
                logger.info(f"收到消息: type={message_type}, need_audio={need_audio}")

                user_content = None
                # 获取对话上下文，用于帮助LLM更好地校正文本
                context = None
                if message_history and message_history[-1]["role"] == "assistant":
                    context = message_history[-1]["content"]
                    logger.debug(f"使用上下文进行文本校正: {context[:100]}...")

                if message_type == "text":
                    raw_text = data.get("content")
                    logger.debug(f"处理文本输入: {raw_text[:100]}...")
                    user_content = await text_correction_service.correct_text(raw_text, context)
                    await manager.send_message({
                        "type": "transcription",
                        "content": user_content,
                        "is_corrected": True
                    }, session_id)
                    logger.debug(f"文本校正完成: {user_content[:100]}...")

                elif message_type == "audio":
                    audio_b64_data = data.get("data")
                    logger.debug(f"处理音频输入: 数据长度={len(audio_b64_data) if audio_b64_data else 0}")
                    audio_bytes = base64.b64decode(audio_b64_data)
                    user_content = await stt_service.transcribe_and_correct(audio_bytes, context)
                    await manager.send_message({
                        "type": "transcription",
                        "content": user_content,
                        "is_corrected": True
                    }, session_id)
                    logger.info(f"语音识别完成: {user_content[:100]}...")
                    need_audio = True
                if user_content:
                    logger.debug(f"开始处理用户输入: {user_content[:100]}...")
                    await _process_user_input(
                        db=db,
                        character=character,
                        conversation_id=conversation_id,
                        user_content=user_content,
                        message_history=message_history,
                        session_id=session_id,
                        need_audio=need_audio
                    )
                    logger.info(f"用户输入处理完成: need_audio={need_audio}")

    except WebSocketDisconnect:
        logger.info(f"WebSocket断开连接: session_id={session_id}")
    except Exception as e:
        logger.error(f"WebSocket处理错误: {e}", exc_info=True)
        await manager.send_message({"error": "内部服务器错误"}, session_id)
    finally:
        if db:
            await db.close()
        manager.disconnect(session_id)
        logger.info(f"WebSocket连接清理完成: session_id={session_id}")


async def _process_user_input(
        db: AsyncSession,
        character: Character,
        conversation_id: int,
        user_content: str,
        message_history: list,
        session_id: str,
        need_audio: bool = False
):
    """
    Handles the core logic of processing user text, generating a response,
    and handling database operations.
    """
    logger.info(f"处理用户输入: need_audio={need_audio}, content_length={len(user_content)}")

    # 获取最近的10条消息（包括用户刚发送的这条）
    recent_messages = await get_recent_messages(db, conversation_id, 10)
    logger.debug(f"获取到 {len(recent_messages)} 条最近消息")

    # 使用Agent生成上下文总结
    context_summary = await generate_context_summary(recent_messages)
    logger.debug(f"生成上下文总结: {context_summary[:100]}...")

    # RAG检索相关知识
    retrieved_chunks = []
    rag_context_prompt = ""

    if character.use_knowledge_base:
        logger.debug(f"开始RAG检索: character_id={character.id}")
        retrieved_chunks = await rag_service.search_knowledge(
            db=db,
            character_id=character.id,
            query=user_content,
            k=character.knowledge_search_k
        )
        logger.debug(f"RAG检索完成: 找到 {len(retrieved_chunks)} 个相关片段")

        if retrieved_chunks:
            rag_context_prompt = await rag_service.build_context_prompt(retrieved_chunks)
            # await manager.send_message({
            #     "type": "context",
            #     "chunks": retrieved_chunks
            # }, session_id)
            logger.debug(f"构建RAG上下文提示: {rag_context_prompt[:100]}...")

    # 保存用户消息
    user_message = Message(
        conversation_id=conversation_id,
        role="user",
        content=user_content
    )
    db.add(user_message)
    await db.commit()
    logger.debug("用户消息已保存到数据库")

    # 添加到历史
    message_history.append({"role": "user", "content": user_content})

    # 构建增强的prompt，结合角色模板、RAG上下文和对话历史总结
    enhanced_prompt_parts = [character.prompt_template]

    if rag_context_prompt:
        enhanced_prompt_parts.append(f"相关知识上下文:\n{rag_context_prompt}")

    if context_summary:
        enhanced_prompt_parts.append(f"对话历史总结:\n{context_summary}")

    enhanced_prompt = "\n\n".join(enhanced_prompt_parts)
    logger.debug(f"构建增强提示: {enhanced_prompt[:200]}...")

    # 生成AI回复
    ai_content = ""
    logger.debug("开始生成AI回复")
    async for chunk in LLMService.generate_response(
            messages=message_history[-10:],  # 只使用最近10条
            character_prompt=enhanced_prompt
    ):
        ai_content += chunk
        await manager.send_message({
            "type": "text_stream",
            "content": chunk
        }, session_id)
    logger.info(f"AI回复生成完成: content_length={len(ai_content)}")

    # 保存AI消息（包含检索到的上下文和对话历史总结）
    ai_message = Message(
        conversation_id=conversation_id,
        role="assistant",
        content=ai_content,
        retrieved_context=retrieved_chunks,
        context_prompt=context_summary  # 存储对话历史总结
    )
    db.add(ai_message)
    await db.commit()
    logger.debug("AI消息已保存到数据库")

    # 生成语音
    if need_audio:
        logger.info("开始生成语音")
        try:
            audio_data = await tts_service.synthesize(
                ai_content,
                character.voice_id
            )
            logger.debug(f"语音合成完成: audio_data_size={len(audio_data)}")

            audio_url = await storage_service.upload_audio(audio_data)
            logger.debug(f"音频上传完成: audio_url={audio_url}")

            ai_message.audio_url = audio_url
            await db.commit()
            logger.debug("音频URL已保存到数据库")

            await manager.send_message({
                "type": "audio",
                "url": audio_url
            }, session_id)
            logger.info("音频消息已发送到客户端")
        except Exception as e:
            logger.error(f"语音合成错误: {e}", exc_info=True)
            await manager.send_message({
                "type": "audio_error",
                "message": "语音生成失败"
            }, session_id)
    else:
        logger.debug("不需要生成语音")

    message_history.append({"role": "assistant", "content": ai_content})