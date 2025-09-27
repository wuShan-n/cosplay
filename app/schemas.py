# app/schemas.py - 更新角色相关的 schema

from pydantic import BaseModel, EmailStr, Field, validator
from typing import Optional, List, Dict, Literal
from datetime import datetime
from enum import Enum


# TTS引擎枚举
class TTSEngineType(str, Enum):
    EDGE_TTS = "edge_tts"
    INDEXTTS2 = "indextts2"


# TTS配置模型
class TTSConfig(BaseModel):
    """IndexTTS2 特定配置"""
    voice_audio_base64: Optional[str] = Field(None, description="音色参考音频(base64)")
    emo_text: Optional[str] = Field(None, description="默认情绪文本描述")
    emo_audio_base64: Optional[str] = Field(None, description="情绪参考音频(base64)")
    emotion_vector: Optional[List[float]] = Field(
        None,
        description="8维情绪向量[开心,愤怒,悲伤,恐惧,厌恶,忧郁,惊讶,平静]",
        min_items=8,
        max_items=8
    )
    emo_alpha: Optional[float] = Field(0.7, ge=0, le=1, description="情绪强度")
    use_random: Optional[bool] = Field(False, description="是否使用随机性")

    @validator('emotion_vector')
    def validate_emotion_vector(cls, v):
        if v and len(v) != 8:
            raise ValueError("情绪向量必须是8维")
        return v


# 用户相关 (保持不变)
class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str


class UserLogin(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    created_at: datetime

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# 角色相关 (更新)

class CharacterCreate(BaseModel):
    name: str
    description: str
    avatar_url: Optional[str] = None
    voice_id: str = "zh-CN-XiaoxiaoNeural"  # Edge-TTS默认声音或IndexTTS2预设ID
    prompt_template: str
    settings: dict = {}
    use_knowledge_base: bool = False
    knowledge_search_k: int = 3
    # TTS配置（新增）
    tts_engine: Optional[TTSEngineType] = Field(TTSEngineType.EDGE_TTS, description="TTS引擎类型")
    tts_config: Optional[TTSConfig] = Field(default_factory=dict, description="TTS引擎特定配置")


class CharacterUpdate(BaseModel):
    """角色更新模型"""
    name: Optional[str] = None
    description: Optional[str] = None
    avatar_url: Optional[str] = None
    voice_id: Optional[str] = None
    prompt_template: Optional[str] = None
    settings: Optional[dict] = None
    use_knowledge_base: Optional[bool] = None
    knowledge_search_k: Optional[int] = None
    tts_engine: Optional[TTSEngineType] = None
    tts_config: Optional[TTSConfig] = None
    is_public: Optional[bool] = None

# 简化的用户信息（用于嵌套显示）
class UserSimpleResponse(BaseModel):
    """简化的用户信息，用于在其他响应中嵌套"""
    id: int
    username: str

    class Config:
        from_attributes = True


# 角色响应模型（更新）
class CharacterResponse(BaseModel):
    id: int
    name: str
    description: str
    avatar_url: Optional[str]
    voice_id: str
    use_knowledge_base: bool
    knowledge_search_k: int
    tts_engine: str
    tts_config: Dict
    is_public: bool
    created_by: Optional[int]  # 创建者ID
    creator: Optional[UserSimpleResponse]  # 创建者信息
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class CharacterDetailResponse(BaseModel):
    """角色详细信息，包含更多配置"""
    id: int
    name: str
    description: str
    avatar_url: Optional[str]
    voice_id: str
    prompt_template: str
    settings: Dict
    use_knowledge_base: bool
    knowledge_search_k: int
    tts_engine: str
    tts_config: Dict
    is_public: bool
    created_by: Optional[int]
    creator: Optional[UserSimpleResponse]
    created_at: datetime
    updated_at: Optional[datetime]
    knowledge_documents_count: Optional[int] = 0
    conversations_count: Optional[int] = 0  # 对话数量
    can_edit: Optional[bool] = False  # 当前用户是否可编辑
    can_delete: Optional[bool] = False  # 当前用户是否可删除

    class Config:
        from_attributes = True


class CharacterListResponse(BaseModel):
    """角色列表响应，包含分页信息"""
    items: List[CharacterResponse]
    total: int
    page: int
    per_page: int

    class Config:
        from_attributes = True

# 知识库相关 (保持不变)
class KnowledgeDocumentCreate(BaseModel):
    title: str
    content: str
    description: Optional[str] = None


class KnowledgeDocumentResponse(BaseModel):
    id: int
    title: str
    description: Optional[str]
    source_type: str
    source_url: Optional[str]
    is_public: bool
    created_by: Optional[int]
    creator: Optional['UserResponse']
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class KnowledgeChunkResponse(BaseModel):
    content: str
    metadata: Dict
    relevance_score: float


# 对话相关 (保持不变)
class MessageResponse(BaseModel):
    id: int
    role: str
    content: str
    audio_url: Optional[str]
    retrieved_context: List[Dict]
    created_at: datetime

    class Config:
        from_attributes = True


class ConversationResponse(BaseModel):
    id: int
    character: CharacterResponse
    messages: List[MessageResponse]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True