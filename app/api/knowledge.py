from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from ..database import get_db
from ..models import Character, KnowledgeDocument, User
from ..schemas import KnowledgeDocumentResponse, KnowledgeDocumentCreate
from ..services.storage_service import storage_service
from ..services.rag_service import rag_service
from .auth import get_current_user

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.post("/characters/{character_id}/upload")
async def upload_knowledge_document(
        character_id: int,
        file: UploadFile = File(...),
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """上传知识库文档"""
    # 检查角色是否存在
    result = await db.execute(
        select(Character).where(Character.id == character_id)
    )
    character = result.scalar_one_or_none()

    if not character:
        raise HTTPException(status_code=404, detail="Character not found")

    # 检查文件类型
    allowed_extensions = ['pdf', 'txt', 'docx']
    file_ext = file.filename.lower().split('.')[-1]
    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"File type not supported. Allowed: {', '.join(allowed_extensions)}"
        )

    # 读取文件内容
    file_content = await file.read()

    # 上传到七牛云
    source_url = await storage_service.upload_document(file_content, file.filename)

    # 处理文档并生成嵌入
    knowledge_doc = await rag_service.process_document(
        db=db,
        character_id=character_id,
        file_content=file_content,
        filename=file.filename,
        source_url=source_url
    )

    # 启用角色的知识库功能
    character.use_knowledge_base = True
    await db.commit()

    return {
        "id": knowledge_doc.id,
        "title": knowledge_doc.title,
        "source_url": knowledge_doc.source_url,
        "chunks_count": len(knowledge_doc.chunks)
    }


@router.post("/characters/{character_id}/manual")
async def add_manual_knowledge(
        character_id: int,
        knowledge: KnowledgeDocumentCreate,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """手动添加知识内容"""
    # 检查角色是否存在
    result = await db.execute(
        select(Character).where(Character.id == character_id)
    )
    character = result.scalar_one_or_none()

    if not character:
        raise HTTPException(status_code=404, detail="Character not found")

    # 添加知识
    knowledge_doc = await rag_service.add_manual_knowledge(
        db=db,
        character_id=character_id,
        title=knowledge.title,
        content=knowledge.content
    )

    # 启用角色的知识库功能
    character.use_knowledge_base = True
    await db.commit()

    return {
        "id": knowledge_doc.id,
        "title": knowledge_doc.title,
        "chunks_count": len(knowledge_doc.chunks)
    }


@router.get("/characters/{character_id}/documents", response_model=List[KnowledgeDocumentResponse])
async def list_knowledge_documents(
        character_id: int,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """获取角色的所有知识库文档"""
    result = await db.execute(
        select(KnowledgeDocument)
        .where(KnowledgeDocument.character_id == character_id)
        .order_by(KnowledgeDocument.created_at.desc())
    )
    documents = result.scalars().all()

    return documents


@router.delete("/documents/{document_id}")
async def delete_knowledge_document(
        document_id: int,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """删除知识库文档"""
    result = await db.execute(
        select(KnowledgeDocument).where(KnowledgeDocument.id == document_id)
    )
    document = result.scalar_one_or_none()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    # 删除文档（级联删除chunks）
    await db.delete(document)
    await db.commit()

    return {"message": "Document deleted successfully"}


@router.post("/characters/{character_id}/search")
async def search_knowledge(
        character_id: int,
        query: str,
        k: int = 3,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """测试知识库搜索"""
    chunks = await rag_service.search_knowledge(
        db=db,
        character_id=character_id,
        query=query,
        k=k
    )

    return {"query": query, "results": chunks}