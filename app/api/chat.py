from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from typing import List

from ..database import get_db
from ..models import User, Character, Conversation, Message
from ..schemas import MessageResponse, ConversationResponse
from .auth import get_current_user

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/conversations/{character_id}", response_model=ConversationResponse)
async def create_conversation(
        character_id: int,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """创建新对话"""
    # 检查角色是否存在，并预加载 creator 关系
    result = await db.execute(
        select(Character)
        .where(Character.id == character_id)
        .options(selectinload(Character.creator))  # 预加载creator关系
    )
    character = result.scalar_one_or_none()

    if not character:
        raise HTTPException(status_code=404, detail="Character not found")

    # 创建对话
    conversation = Conversation(
        user_id=current_user.id,
        character_id=character_id
    )
    db.add(conversation)
    await db.commit()

    # 重新查询以加载所需的关系，包括character的creator
    result = await db.execute(
        select(Conversation)
        .where(Conversation.id == conversation.id)
        .options(
            selectinload(Conversation.character).selectinload(Character.creator),  # 嵌套加载creator
            selectinload(Conversation.messages)
        )
    )
    conversation = result.scalar_one()

    return conversation


@router.get("/conversations", response_model=List[ConversationResponse])
async def list_conversations(
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """获取用户的所有对话"""
    # 使用 selectinload 预加载需要的关系，包括嵌套的creator
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == current_user.id)
        .order_by(Conversation.updated_at.desc())
        .options(
            selectinload(Conversation.character).selectinload(Character.creator),  # 嵌套加载creator
            selectinload(Conversation.messages)  # 如果不需要消息，可以移除这行
        )
    )
    conversations = result.scalars().all()

    return conversations


@router.get("/conversations/{conversation_id}/messages", response_model=List[MessageResponse])
async def get_messages(
        conversation_id: int,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """获取对话消息历史"""
    # 验证对话属于当前用户
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == current_user.id
        )
    )
    conversation = result.scalar_one_or_none()

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # 获取消息
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    )
    messages = result.scalars().all()

    return messages


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
        conversation_id: int,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """删除对话及其所有消息"""
    # 验证对话存在且属于当前用户
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == current_user.id
        )
    )
    conversation = result.scalar_one_or_none()

    if not conversation:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found or you don't have permission to delete it"
        )

    # 删除对话（由于cascade设置，相关消息会自动删除）
    await db.delete(conversation)
    await db.commit()

    return {"message": f"Conversation {conversation_id} deleted successfully"}