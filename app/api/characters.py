# app/api/characters.py
import base64
from typing import List, Optional, Dict

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy import select, func, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, attributes

from .auth import get_current_user
from ..database import get_db
from ..models import Character, User, Conversation
from ..schemas import (
    CharacterCreate,
    CharacterUpdate,
    CharacterResponse,
    CharacterDetailResponse,
    CharacterListResponse,
    TTSConfig,
    TTSEngineType
)
from ..services.storage_service import storage_service

router = APIRouter(prefix="/characters", tags=["characters"])


@router.get("/", response_model=CharacterListResponse)
async def list_characters(
        page: int = Query(1, ge=1, description="页码"),
        per_page: int = Query(20, ge=1, le=100, description="每页数量"),
        search: Optional[str] = Query(None, description="搜索关键词"),
        include_private: bool = Query(False, description="是否包含私有角色"),
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """获取角色列表（公开角色 + 自己的私有角色）"""

    # 构建查询条件
    conditions = []

    if include_private:
        # 包含私有角色：公开的 + 自己创建的
        conditions.append(
            or_(
                Character.is_public == True,
                Character.created_by == current_user.id
            )
        )
    else:
        # 只显示公开角色
        conditions.append(Character.is_public == True)

    # 搜索条件
    if search:
        conditions.append(
            or_(
                Character.name.ilike(f"%{search}%"),
                Character.description.ilike(f"%{search}%")
            )
        )

    # 计算总数
    count_query = select(func.count()).select_from(Character).where(and_(*conditions))
    total_result = await db.execute(count_query)
    total = total_result.scalar()

    # 分页查询
    offset = (page - 1) * per_page
    query = (
        select(Character)
        .where(and_(*conditions))
        .options(selectinload(Character.creator))  # 预加载创建者信息
        .order_by(Character.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )

    result = await db.execute(query)
    characters = result.scalars().all()

    return CharacterListResponse(
        items=characters,
        total=total,
        page=page,
        per_page=per_page
    )


@router.get("/my", response_model=List[CharacterResponse])
async def list_my_characters(
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """获取我创建的所有角色"""
    result = await db.execute(
        select(Character)
        .where(Character.created_by == current_user.id)
        .options(selectinload(Character.creator))
        .order_by(Character.created_at.desc())
    )
    characters = result.scalars().all()
    return characters


@router.get("/{character_id}", response_model=CharacterDetailResponse)
async def get_character(
        character_id: int,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """获取单个角色详情"""
    # 使用 joinedload 一次性加载所有需要的关系
    result = await db.execute(
        select(Character)
        .where(Character.id == character_id)
        .options(
            selectinload(Character.creator),
            selectinload(Character.knowledge_documents),
            selectinload(Character.conversations)
        )
    )
    character = result.scalar_one_or_none()

    if not character:
        raise HTTPException(status_code=404, detail="Character not found")

    # 检查访问权限（私有角色只有创建者可以看到详情）
    if not character.is_public and character.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="No permission to view this private character")

    # 判断编辑和删除权限
    can_edit = character.created_by == current_user.id
    can_delete = character.created_by == current_user.id

    # 构建响应
    response = CharacterDetailResponse(
        id=character.id,
        name=character.name,
        description=character.description,
        avatar_url=character.avatar_url,
        voice_id=character.voice_id,
        prompt_template=character.prompt_template,
        settings=character.settings or {},
        use_knowledge_base=character.use_knowledge_base,
        knowledge_search_k=character.knowledge_search_k,
        tts_engine=character.tts_engine or "edge_tts",
        tts_config=character.tts_config or {},
        is_public=character.is_public,
        created_by=character.created_by,
        creator=character.creator,
        created_at=character.created_at,
        updated_at=character.updated_at,
        knowledge_documents_count=len(character.knowledge_documents),
        conversations_count=len(character.conversations),
        can_edit=can_edit,
        can_delete=can_delete
    )

    return response


@router.post("/", response_model=CharacterDetailResponse)
async def create_character(
        character: CharacterCreate,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """创建新角色"""

    # (*** 修改 ***) 处理TTS配置中的Base64数据
    tts_config_dict = character.tts_config.dict() if character.tts_config else {}
    processed_tts_config = await _process_tts_audio_base64(tts_config_dict)

    # 验证TTS配置 (基于处理后的配置)
    if character.tts_engine == TTSEngineType.INDEXTTS2:
        if not processed_tts_config.get("voice_audio_url") and not character.voice_id:
            raise HTTPException(
                status_code=400,
                detail="IndexTTS2 requires either voice_audio_base64 (to be converted to URL) or a valid voice_id preset"
            )

    # 创建角色，设置创建者
    db_character = Character(
        name=character.name,
        description=character.description,
        avatar_url=character.avatar_url,
        voice_id=character.voice_id,
        prompt_template=character.prompt_template,
        settings=character.settings,
        use_knowledge_base=character.use_knowledge_base,
        knowledge_search_k=character.knowledge_search_k,
        tts_engine=character.tts_engine.value if character.tts_engine else "edge_tts",
        tts_config=processed_tts_config,
        is_public=True,
        created_by=current_user.id
    )

    db.add(db_character)
    await db.commit()
    await db.refresh(db_character)

    # 加载创建者信息
    await db.refresh(db_character, ["creator"])

    return CharacterDetailResponse(
        id=db_character.id,
        name=db_character.name,
        description=db_character.description,
        avatar_url=db_character.avatar_url,
        voice_id=db_character.voice_id,
        prompt_template=db_character.prompt_template,
        settings=db_character.settings,
        use_knowledge_base=db_character.use_knowledge_base,
        knowledge_search_k=db_character.knowledge_search_k,
        tts_engine=db_character.tts_engine,
        tts_config=db_character.tts_config,
        is_public=db_character.is_public,
        created_by=db_character.created_by,
        creator=db_character.creator,
        created_at=db_character.created_at,
        updated_at=db_character.updated_at,
        knowledge_documents_count=0,
        conversations_count=0,
        can_edit=True,  # 创建者可以编辑
        can_delete=True  # 创建者可以删除
    )


@router.put("/{character_id}", response_model=CharacterDetailResponse)
async def update_character(
        character_id: int,
        character_update: CharacterUpdate,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """更新角色信息（只有创建者可以更新）"""
    result = await db.execute(
        select(Character)
        .where(Character.id == character_id)
        .options(selectinload(Character.creator))
    )
    character = result.scalar_one_or_none()

    if not character:
        raise HTTPException(status_code=404, detail="Character not found")

    # 权限检查：只有创建者可以更新
    if character.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="No permission to update this character")

    # 更新字段
    update_data = character_update.dict(exclude_unset=True)

    # 处理TTS配置
    if "tts_config" in update_data and update_data["tts_config"]:
        # 获取当前数据库中的配置，如果不存在则为空字典
        current_config = character.tts_config.copy() if character.tts_config else {}

        # 获取更新数据
        update_config_data = update_data["tts_config"]

        # 处理可能存在的Base64数据
        processed_updates = await _process_tts_audio_base64(update_config_data)

        # 将处理后的更新合并到当前配置中
        current_config.update(processed_updates)

        # 将合并后的完整配置赋值给角色模型
        character.tts_config = current_config

        # 标记JSON字段已修改，确保SQLAlchemy能检测到变化
        attributes.flag_modified(character, "tts_config")

        # 从主更新数据中移除tts_config，因为它已被特殊处理
        del update_data["tts_config"]

    # 处理TTS引擎枚举
    if "tts_engine" in update_data and update_data["tts_engine"]:
        update_data["tts_engine"] = update_data["tts_engine"].value

    # 应用其余的更新
    for field, value in update_data.items():
        setattr(character, field, value)

    await db.commit()

    # 重新加载关系数据
    result = await db.execute(
        select(Character)
        .where(Character.id == character_id)
        .options(
            selectinload(Character.creator),
            selectinload(Character.knowledge_documents),
            selectinload(Character.conversations)
        )
    )
    character = result.scalar_one()

    return CharacterDetailResponse(
        id=character.id,
        name=character.name,
        description=character.description,
        avatar_url=character.avatar_url,
        voice_id=character.voice_id,
        prompt_template=character.prompt_template,
        settings=character.settings,
        use_knowledge_base=character.use_knowledge_base,
        knowledge_search_k=character.knowledge_search_k,
        tts_engine=character.tts_engine,
        tts_config=character.tts_config,
        is_public=character.is_public,
        created_by=character.created_by,
        creator=character.creator,
        created_at=character.created_at,
        updated_at=character.updated_at,
        knowledge_documents_count=len(character.knowledge_documents),
        conversations_count=len(character.conversations),
        can_edit=True,
        can_delete=True
    )


@router.delete("/{character_id}")
async def delete_character(
        character_id: int,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """删除角色（只有创建者可以删除）"""
    result = await db.execute(
        select(Character).where(Character.id == character_id)
    )
    character = result.scalar_one_or_none()

    if not character:
        raise HTTPException(status_code=404, detail="Character not found")

    # 权限检查：只有创建者可以删除
    if character.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="No permission to delete this character")

    # 检查是否有活跃的对话
    conversations_count = await db.execute(
        select(func.count()).select_from(Conversation).where(Conversation.character_id == character_id)
    )
    if conversations_count.scalar() > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete character with {conversations_count.scalar()} active conversations. Please delete conversations first."
        )

    await db.delete(character)
    await db.commit()

    return {"message": f"Character {character_id} deleted successfully"}


@router.post("/{character_id}/toggle-visibility")
async def toggle_character_visibility(
        character_id: int,
        is_public: bool,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """切换角色的公开/私有状态（只有创建者可以操作）"""
    result = await db.execute(
        select(Character).where(Character.id == character_id)
    )
    character = result.scalar_one_or_none()

    if not character:
        raise HTTPException(status_code=404, detail="Character not found")

    # 权限检查
    if character.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="No permission to change visibility of this character")

    character.is_public = is_public
    await db.commit()

    return {
        "id": character.id,
        "name": character.name,
        "is_public": character.is_public,
        "message": f"Character is now {'public' if is_public else 'private'}"
    }



@router.post("/{character_id}/avatar")
async def upload_avatar(
        character_id: int,
        file: UploadFile = File(...),
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """上传角色头像（只有创建者可以上传）"""
    result = await db.execute(
        select(Character).where(Character.id == character_id)
    )
    character = result.scalar_one_or_none()

    if not character:
        raise HTTPException(status_code=404, detail="Character not found")

    # 权限检查
    if character.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="No permission to upload avatar for this character")

    # 上传到七牛云
    image_data = await file.read()
    avatar_url = await storage_service.upload_avatar(image_data)

    # 更新角色头像URL
    character.avatar_url = avatar_url
    await db.commit()

    return {"avatar_url": avatar_url}


@router.post("/{character_id}/voice-sample")
async def upload_voice_sample(
        character_id: int,
        file: UploadFile = File(...),
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """上传角色音色样本（只有创建者可以上传）"""
    result = await db.execute(
        select(Character).where(Character.id == character_id)
    )
    character = result.scalar_one_or_none()

    if not character:
        raise HTTPException(status_code=404, detail="Character not found")

    # 权限检查
    if character.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="No permission to upload voice sample for this character")

    # 检查文件类型
    allowed_extensions = ['wav', 'mp3', 'webm', 'm4a']
    file_ext = file.filename.lower().split('.')[-1]
    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"File type not supported. Allowed: {', '.join(allowed_extensions)}"
        )

    # 读取音频文件并直接上传到七牛云
    audio_data = await file.read()
    audio_url = await storage_service.upload_audio(audio_data, filename=file.filename)

    # 更新角色的TTS配置
    if not character.tts_config:
        character.tts_config = {}

    # (*** 修改 ***) 保存URL而不是base64
    character.tts_config["voice_audio_url"] = audio_url

    character.tts_engine = "indextts2"  # 自动切换到IndexTTS2引擎

    # 标记JSON字段已修改
    attributes.flag_modified(character, "tts_config")

    await db.commit()

    return {
        "message": "Voice sample uploaded successfully",
        "tts_engine": character.tts_engine,
        "voice_audio_url": audio_url  # 返回URL
    }

async def _process_tts_audio_base64(tts_config: Dict) -> Dict:
    """处理TTS配置中的base64数据，上传到云存储并替换为URL"""
    if not tts_config:
        return {}

    # 处理音色音频
    if tts_config.get("voice_audio_base64"):
        try:
            audio_data = base64.b64decode(tts_config["voice_audio_base64"])
            audio_url = await storage_service.upload_audio(audio_data)
            tts_config["voice_audio_url"] = audio_url
            # 删除临时的base64数据
            del tts_config["voice_audio_base64"]
        except (ValueError, TypeError) as e:
            raise HTTPException(status_code=400, detail=f"Invalid voice_audio_base64 format: {e}")

    # 处理情绪参考音频
    if tts_config.get("emo_audio_base64"):
        try:
            audio_data = base64.b64decode(tts_config["emo_audio_base64"])
            audio_url = await storage_service.upload_audio(audio_data)
            tts_config["emo_audio_url"] = audio_url
            # 删除临শনেরbase64数据
            del tts_config["emo_audio_base64"]
        except (ValueError, TypeError) as e:
            raise HTTPException(status_code=400, detail=f"Invalid emo_audio_base64 format: {e}")

    return tts_config