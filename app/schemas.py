from pydantic import BaseModel, EmailStr
from typing import Optional, List, Dict
from datetime import datetime


# 用户相关
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


# 角色相关
class CharacterCreate(BaseModel):
    name: str
    description: str
    avatar_url: Optional[str] = None
    voice_id: str = "zh-CN-XiaoxiaoNeural"  # 默认Edge-TTS声音
    prompt_template: str
    settings: dict = {}
    use_knowledge_base: bool = False
    knowledge_search_k: int = 3


class CharacterResponse(BaseModel):
    id: int
    name: str
    description: str
    avatar_url: Optional[str]
    voice_id: str
    use_knowledge_base: bool
    knowledge_search_k: int
    created_at: datetime

    class Config:
        from_attributes = True



# 知识库相关
class KnowledgeDocumentCreate(BaseModel):
    title: str
    content: str
    description: Optional[str] = None


class KnowledgeDocumentResponse(BaseModel):
    """知识库详细信息"""
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

# 对话相关

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