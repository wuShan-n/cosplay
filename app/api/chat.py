from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from ..database import get_db
from ..models import User, Character, Conversation, Message
from ..schemas import  MessageResponse, ConversationResponse
from .auth import get_current_user

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/conversations/{character_id}", response_model=ConversationResponse)
async def create_conversation(
        character_id: int,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """创建新对话"""
    # 检查角色是否存在
    result = await db.execute(
        select(Character).where(Character.id == character_id)
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
    await db.refresh(conversation)

    return conversation


@router.get("/conversations", response_model=List[ConversationResponse])
async def list_conversations(
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """获取用户的所有对话"""
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == current_user.id)
        .order_by(Conversation.updated_at.desc())
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