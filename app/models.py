from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean, JSON, Float, Table
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from pgvector.sqlalchemy import Vector
from datetime import datetime
import uuid
from .database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # 改为默认的 lazy loading
    conversations = relationship("Conversation", back_populates="user")


# 多对多关联表
character_knowledge_association = Table(
    'character_knowledge_association',
    Base.metadata,
    Column('character_id', Integer, ForeignKey('characters.id'), primary_key=True),
    Column('knowledge_document_id', Integer, ForeignKey('knowledge_documents.id'), primary_key=True),
    Column('created_at', DateTime, default=datetime.utcnow)
)


# 在 app/models.py 的 Character 模型中添加 created_by 字段

class Character(Base):
    __tablename__ = "characters"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True, nullable=False)
    description = Column(Text)
    avatar_url = Column(String)
    voice_id = Column(String)  # Edge-TTS voice ID 或 IndexTTS2 voice preset ID
    prompt_template = Column(Text, nullable=False)
    settings = Column(JSON, default={})
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)  # 新增更新时间
    is_public = Column(Boolean, default=True)

    # 创建者字段（新增）
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)  # 添加索引便于查询

    # RAG 设置
    use_knowledge_base = Column(Boolean, default=False)
    knowledge_search_k = Column(Integer, default=3)

    # TTS 引擎配置
    tts_engine = Column(String, default="edge_tts")  # 'edge_tts' 或 'indextts2'
    tts_config = Column(JSON, default={})  # 存储引擎特定的配置

    # 关系字段
    conversations = relationship("Conversation", back_populates="character", cascade="all, delete-orphan")
    knowledge_documents = relationship(
        "KnowledgeDocument",
        secondary=character_knowledge_association,
        back_populates="characters"
    )
    # 创建者关系（新增）
    creator = relationship("User", foreign_keys=[created_by], backref="created_characters")


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False, index=True)  # 添加索引便于搜索
    description = Column(Text)  # 知识库描述
    source_type = Column(String)  # 'pdf', 'txt', 'docx', 'manual'
    source_url = Column(String)  # 七牛云存储URL
    is_public = Column(Boolean, default=False)  # 是否公开，便于知识库共享
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)  # 创建者
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 改为默认的 lazy loading
    characters = relationship(
        "Character",
        secondary=character_knowledge_association,
        back_populates="knowledge_documents"
    )
    chunks = relationship("KnowledgeChunk", back_populates="document", cascade="all, delete-orphan")
    creator = relationship("User", foreign_keys=[created_by])


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("knowledge_documents.id"), index=True)  # 添加索引
    content = Column(Text, nullable=False)
    chunk_metadata = Column(JSON, default={})  # 页码、章节等元数据
    embedding = Column(Vector(1536))  # 使用 pgvector 存储向量
    chunk_index = Column(Integer)  # 在文档中的顺序

    document = relationship("KnowledgeDocument", back_populates="chunks")


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    character_id = Column(Integer, ForeignKey("characters.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 改为默认的 lazy loading
    user = relationship("User", back_populates="conversations")
    character = relationship("Character", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"))
    role = Column(String, nullable=False)  # "user" or "assistant"
    content = Column(Text, nullable=False)
    audio_url = Column(String)  # 音频文件URL（七牛云）
    retrieved_context = Column(JSON, default=[])  # RAG检索到的上下文
    created_at = Column(DateTime, default=datetime.utcnow)
    conversation = relationship("Conversation", back_populates="messages")
    context_prompt = Column(String(1000), nullable=True)