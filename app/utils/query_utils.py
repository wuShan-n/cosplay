"""
查询优化工具模块
提供统一的数据加载方法，避免 N+1 查询问题
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload, joinedload, subqueryload
from typing import Optional, List
from ..models import Character, Conversation, Message, KnowledgeDocument, User


class QueryUtils:
    """查询工具类，提供优化的数据库查询方法"""

    @staticmethod
    async def get_character_with_documents(
            db: AsyncSession,
            character_id: int
    ) -> Optional[Character]:
        """获取角色及其关联的知识库文档"""
        result = await db.execute(
            select(Character)
            .where(Character.id == character_id)
            .options(selectinload(Character.knowledge_documents))
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_conversation_with_messages(
            db: AsyncSession,
            conversation_id: int,
            message_limit: Optional[int] = None
    ) -> Optional[Conversation]:
        """获取对话及其消息（可限制消息数量）"""
        # 基础查询
        query = select(Conversation).where(Conversation.id == conversation_id)

        if message_limit:
            # 如果需要限制消息数量，使用子查询
            query = query.options(
                selectinload(Conversation.character),
                selectinload(Conversation.user)
            )
            result = await db.execute(query)
            conversation = result.scalar_one_or_none()

            if conversation:
                # 单独查询有限的消息
                messages_result = await db.execute(
                    select(Message)
                    .where(Message.conversation_id == conversation_id)
                    .order_by(Message.created_at.desc())
                    .limit(message_limit)
                )
                messages = list(messages_result.scalars().all())
                messages.reverse()  # 恢复时间顺序
                conversation.messages = messages

            return conversation
        else:
            # 加载所有消息
            query = query.options(
                selectinload(Conversation.messages),
                selectinload(Conversation.character),
                selectinload(Conversation.user)
            )
            result = await db.execute(query)
            return result.scalar_one_or_none()

    @staticmethod
    async def get_conversation_with_character(
            db: AsyncSession,
            conversation_id: int
    ) -> Optional[Conversation]:
        """仅获取对话和角色信息，不加载消息"""
        result = await db.execute(
            select(Conversation)
            .where(Conversation.id == conversation_id)
            .options(selectinload(Conversation.character))
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_user_conversations(
            db: AsyncSession,
            user_id: int,
            include_messages: bool = False
    ) -> List[Conversation]:
        """获取用户的所有对话"""
        query = (
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc())
            .options(selectinload(Conversation.character))
        )

        if include_messages:
            query = query.options(selectinload(Conversation.messages))

        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def get_document_with_chunks(
            db: AsyncSession,
            document_id: int
    ) -> Optional[KnowledgeDocument]:
        """获取文档及其所有chunks"""
        result = await db.execute(
            select(KnowledgeDocument)
            .where(KnowledgeDocument.id == document_id)
            .options(selectinload(KnowledgeDocument.chunks))
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_public_documents(
            db: AsyncSession,
            skip: int = 0,
            limit: int = 20,
            include_creator: bool = False
    ) -> List[KnowledgeDocument]:
        """获取公开的知识库文档"""
        query = (
            select(KnowledgeDocument)
            .where(KnowledgeDocument.is_public == True)
            .order_by(KnowledgeDocument.created_at.desc())
            .offset(skip)
            .limit(limit)
        )

        if include_creator:
            query = query.options(selectinload(KnowledgeDocument.creator))

        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def get_character_knowledge_documents(
            db: AsyncSession,
            character_id: int
    ) -> List[KnowledgeDocument]:
        """获取角色关联的所有知识库文档"""
        character = await QueryUtils.get_character_with_documents(db, character_id)
        return character.knowledge_documents if character else []


# 创建单例实例
query_utils = QueryUtils()