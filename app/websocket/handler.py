from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
import json
import redis.asyncio as redis
import base64
import logging
import re
from ..services.context_agent import ContextAgent
from ..database import AsyncSessionLocal
from ..models import Character, Conversation, Message
from ..services.llm_service import LLMService
from ..services.stt_service import stt_service
from ..services.tts_service import tts_service
from ..services.storage_service import storage_service
from ..services.rag_service import rag_service
from ..services.text_correction_service import text_correction_service
from ..utils.query_utils import query_utils
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
    使用优化的查询避免 N+1 问题
    """
    # 使用优化的查询工具
    conversation = await query_utils.get_conversation_with_character(db, conversation_id)

    if not conversation:
        raise ValueError("Conversation not found")

    if not conversation.character:
        raise ValueError("Character not found")

    return conversation, conversation.character


async def get_recent_messages(db: AsyncSession, conversation_id: int, limit: int = 10):
    """获取最近的消息 - 直接查询，不预加载关系"""
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


async def save_and_upload_audio(audio_bytes: bytes, role: str = "user") -> str:
    """
    保存音频到七牛云并返回URL

    参数:
        audio_bytes: 音频二进制数据
        role: 角色类型，用于生成文件名前缀

    返回:
        音频URL
    """
    try:
        # 根据角色生成不同的文件名前缀
        prefix = "user_audio" if role == "user" else "assistant_audio"
        filename = f"audio/{prefix}/{role}_audio.webm" if role == "user" else None

        audio_url = await storage_service.upload_audio(audio_bytes, filename)
        logger.debug(f"{role} 音频上传成功: {audio_url}")
        return audio_url
    except Exception as e:
        logger.error(f"{role} 音频上传失败: {e}")
        return None


async def _clean_text_for_tts(text: str) -> str:
    """
    使用LLM清理文本中的特殊符号，防止语音合成时读出

    参数:
        text: 需要清理的文本

    返回:
        清理后的文本
    """
    # 首先使用简单的正则表达式移除明显的特殊符号
    # 移除星号、井号等常见特殊符号
    cleaned = re.sub(r'[*#@$%^&_+={}\[\]|\\<>~`]', '', text)

    # 如果文本已经很干净，直接返回
    if cleaned == text:
        return text

    # 如果文本有特殊符号，使用LLM进行更智能的清理
    prompt = f"""请帮我清理以下文本，移除所有不适合语音朗读的特殊符号和标记，但保留正常的标点符号（如句号、逗号、问号等）。

需要清理的文本：
{text}

请只返回清理后的文本，不要添加任何解释或额外内容。"""

    try:
        # 调用LLM进行清理
        cleaned_text = ""
        async for chunk in LLMService.generate_response(
                messages=[{"role": "user", "content": prompt}],
                character_prompt="你是一个文本清理专家，擅长移除不适合语音朗读的特殊符号。",
                stream=False
        ):
            cleaned_text += chunk

        return cleaned_text.strip()
    except Exception as e:
        logger.error(f"使用LLM清理文本时出错: {e}")
        # 如果LLM调用失败，返回正则表达式清理的版本
        return cleaned


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
            # 使用优化的查询获取对话和角色信息
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
                        "created_at": msg.created_at.isoformat(),
                        "audio_url": msg.audio_url
                    }
                    for msg in recent_messages
                ]
                await manager.send_message({
                    "type": "history",
                    "messages": history_payload
                }, session_id)
                logger.info(f"已将 {len(history_payload)} 条历史消息发送到 session_id={session_id}")

            while True:
                data = await websocket.receive_json()
                message_type = data.get("type")
                need_audio = data.get("need_audio", False)
                logger.info(f"收到消息: type={message_type}, need_audio={need_audio}")

                user_content = None
                user_audio_url = None  # 用户音频URL

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

                    # 1. 语音识别和文本校正
                    user_content = await stt_service.transcribe_and_correct(audio_bytes, context)
                    await manager.send_message({
                        "type": "transcription",
                        "content": user_content,
                        "is_corrected": True
                    }, session_id)
                    logger.info(f"语音识别完成: {user_content[:100]}...")

                    # 2. 上传用户音频到七牛云
                    user_audio_url = await save_and_upload_audio(audio_bytes, role="user")
                    if user_audio_url:
                        await manager.send_message({
                            "type": "audio",
                            "url": user_audio_url
                        }, session_id)
                        logger.info(f"用户音频已上传: {user_audio_url}")

                need_audio = True

                if user_content:
                    logger.debug(f"开始处理用户输入: {user_content[:100]}...")
                    await _process_user_input(
                        db=db,
                        character=character,
                        conversation_id=conversation_id,
                        user_content=user_content,
                        user_audio_url=user_audio_url,  # 传递用户音频URL
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
        user_audio_url: str,  # 新增参数：用户音频URL
        message_history: list,
        session_id: str,
        need_audio: bool = False
):
    """
    Handles the core logic of processing user text, generating a response,
    and handling database operations.
    """
    logger.info(
        f"处理用户输入: need_audio={need_audio}, content_length={len(user_content)}, has_audio={bool(user_audio_url)}")

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
        # 需要时才加载知识库文档
        character_with_docs = await query_utils.get_character_with_documents(db, character.id)
        if character_with_docs and character_with_docs.knowledge_documents:
            retrieved_chunks = await rag_service.search_knowledge(
                db=db,
                character_id=character.id,
                query=user_content,
                k=character.knowledge_search_k
            )
            logger.debug(f"RAG检索完成: 找到 {len(retrieved_chunks)} 个相关片段")

            if retrieved_chunks:
                rag_context_prompt = await rag_service.build_context_prompt(retrieved_chunks)
                logger.debug(f"构建RAG上下文提示: {rag_context_prompt[:100]}...")

    # 保存用户消息（包含音频URL）
    user_message = Message(
        conversation_id=conversation_id,
        role="user",
        content=user_content,
        audio_url=user_audio_url  # 保存用户音频URL
    )
    db.add(user_message)
    await db.commit()
    logger.debug(f"用户消息已保存到数据库，audio_url={user_audio_url}")

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

    # 初始化AI音频URL
    ai_audio_url = None

    # 生成AI语音（如果需要）
    if need_audio:
        logger.info(f"开始生成AI语音，使用引擎: {character.tts_engine or 'edge_tts'}")
        try:
            # 在生成语音前，先使用LLM清理文本中的特殊符号
            logger.debug("开始清理文本中的特殊符号")
            cleaned_text = await _clean_text_for_tts(ai_content)
            logger.debug(f"文本清理完成: {cleaned_text[:100]}...")

            # 准备TTS参数
            tts_kwargs = {}

            # 根据角色配置选择TTS引擎
            tts_engine = character.tts_engine or "edge_tts"

            if tts_engine == "indextts2":
                # 使用IndexTTS2引擎
                from ..services.tts_service import TTSEngine

                # 从角色配置中获取TTS特定参数
                tts_config = character.tts_config or {}

                # 动态情绪控制（可以根据对话内容分析情绪）
                # 这里可以加入情绪分析逻辑
                emo_text = tts_config.get("emo_text")

                # 如果有特定的情绪需求，可以在这里动态设置
                # 例如，根据AI回复的内容判断情绪
                if "开心" in ai_content or "高兴" in ai_content:
                    emo_text = "开心地说"
                elif "抱歉" in ai_content or "对不起" in ai_content:
                    emo_text = "歉意地说"
                elif "?" in ai_content or "？" in ai_content:
                    emo_text = "好奇地问"

                audio_data = await tts_service.synthesize(
                    text=cleaned_text,  # 使用清理后的文本
                    voice_id=character.voice_id,
                    engine=TTSEngine.INDEXTTS2,
                    voice_audio_url=tts_config.get("voice_audio_url"),  # <--- 新增此行
                    emo_audio_url=tts_config.get("emo_audio_url"),  # <--- 建议也加上情绪音频URL
                    emo_text=emo_text or tts_config.get("emo_text"),
                    emo_alpha=tts_config.get("emo_alpha", 0.7),
                    emotion_vector=tts_config.get("emotion_vector"),
                    use_random=tts_config.get("use_random", False)
                )
            else:
                # 使用Edge-TTS引擎（默认）
                audio_data = await tts_service.synthesize(
                    text=cleaned_text,  # 使用清理后的文本
                    voice_id=character.voice_id
                )

            logger.debug(f"语音合成完成: audio_data_size={len(audio_data)}")

            # 上传音频
            ai_audio_url = await save_and_upload_audio(audio_data, role="assistant")
            if ai_audio_url:
                await manager.send_message({
                    "type": "audio",
                    "url": ai_audio_url
                }, session_id)
                logger.info(f"AI音频消息已发送到客户端: {ai_audio_url}")
            else:
                raise Exception("音频上传失败")

        except Exception as e:
            logger.error(f"语音合成错误 (引擎: {character.tts_engine}): {e}", exc_info=True)
            await manager.send_message({
                "type": "audio_error",
                "message": f"语音生成失败 ({character.tts_engine})"
            }, session_id)
    else:
        logger.debug("不需要生成语音")

    # 保存AI消息（包含检索到的上下文、对话历史总结和音频URL）
    ai_message = Message(
        conversation_id=conversation_id,
        role="assistant",
        content=ai_content,
        audio_url=ai_audio_url,  # 保存AI音频URL
        retrieved_context=retrieved_chunks,
        context_prompt=context_summary  # 存储对话历史总结
    )
    db.add(ai_message)
    await db.commit()
    logger.debug(f"AI消息已保存到数据库，audio_url={ai_audio_url}")

    message_history.append({"role": "assistant", "content": ai_content})