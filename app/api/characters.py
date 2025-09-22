from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from ..database import get_db
from ..models import Character, User
from ..schemas import CharacterCreate, CharacterResponse
from ..services.storage_service import storage_service
from .auth import get_current_user

router = APIRouter(prefix="/characters", tags=["characters"])


@router.get("/", response_model=List[CharacterResponse])
async def list_characters(
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """获取所有公开角色"""
    result = await db.execute(
        select(Character).where(Character.is_public == True)
    )
    characters = result.scalars().all()
    return characters


@router.get("/{character_id}", response_model=CharacterResponse)
async def get_character(
        character_id: int,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """获取单个角色详情"""
    result = await db.execute(
        select(Character).where(Character.id == character_id)
    )
    character = result.scalar_one_or_none()

    if not character:
        raise HTTPException(status_code=404, detail="Character not found")

    return character


@router.post("/", response_model=CharacterResponse)
async def create_character(
        character: CharacterCreate,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """创建新角色"""
    db_character = Character(**character.dict())
    db.add(db_character)
    await db.commit()
    await db.refresh(db_character)

    return db_character


@router.post("/{character_id}/avatar")
async def upload_avatar(
        character_id: int,
        file: UploadFile = File(...),
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """上传角色头像"""
    result = await db.execute(
        select(Character).where(Character.id == character_id)
    )
    character = result.scalar_one_or_none()

    if not character:
        raise HTTPException(status_code=404, detail="Character not found")

    # 上传到七牛云
    image_data = await file.read()
    avatar_url = await storage_service.upload_avatar(image_data)

    # 更新角色头像URL
    character.avatar_url = avatar_url
    await db.commit()

    return {"avatar_url": avatar_url}