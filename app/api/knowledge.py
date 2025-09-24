from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional

from ..database import get_db
from ..models import Character, KnowledgeDocument, User
from ..schemas import KnowledgeDocumentResponse, KnowledgeDocumentCreate
from ..services.storage_service import storage_service
from ..services.rag_service import rag_service
from .auth import get_current_user

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.post("/upload")
async def upload_knowledge_document(
        file: UploadFile = File(...),
        description: Optional[str] = Form(None),
        is_public: Optional[bool] = Form(None),
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """上传知识库文档（独立于角色）"""

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
        file_content=file_content,
        filename=file.filename,
        source_url=source_url,
        user_id=current_user.id,
        description=description,
        is_public=is_public
    )

    await db.commit()

    return {
        "id": knowledge_doc.id,
        "title": knowledge_doc.title,
        "description": knowledge_doc.description,
        "source_url": knowledge_doc.source_url,
        "is_public": knowledge_doc.is_public,
        "chunks_count": len(knowledge_doc.chunks)
    }


@router.get("/public", response_model=List[KnowledgeDocumentResponse])
async def list_public_knowledge_documents(
        skip: int = Query(0, ge=0),
        limit: int = Query(20, ge=1, le=100),
        db: AsyncSession = Depends(get_db)
):
    """获取所有公开的知识库文档"""
    documents = await rag_service.get_public_knowledge_documents(db, skip, limit)
    return documents


@router.get("/my", response_model=List[KnowledgeDocumentResponse])
async def list_my_knowledge_documents(
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """获取我创建的所有知识库文档"""
    result = await db.execute(
        select(KnowledgeDocument)
        .where(KnowledgeDocument.created_by == current_user.id)
        .order_by(KnowledgeDocument.created_at.desc())
    )
    documents = result.scalars().all()
    return documents


@router.post("/characters/{character_id}/link/{document_id}")
async def link_knowledge_to_character(
        character_id: int,
        document_id: int,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """将知识库关联到角色"""

    # 检查权限：只能关联公开的知识库或自己创建的知识库
    document = await db.get(KnowledgeDocument, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if not document.is_public and document.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="No permission to link this document")

    # 检查角色是否存在
    character = await db.get(Character, character_id)
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")

    # 关联知识库到角色
    success = await rag_service.link_knowledge_to_character(db, character_id, document_id)

    if success:
        return {"message": "Knowledge document linked to character successfully"}
    else:
        raise HTTPException(status_code=400, detail="Failed to link document")


@router.delete("/characters/{character_id}/unlink/{document_id}")
async def unlink_knowledge_from_character(
        character_id: int,
        document_id: int,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """解除知识库与角色的关联"""

    success = await rag_service.unlink_knowledge_from_character(db, character_id, document_id)

    if success:
        return {"message": "Knowledge document unlinked from character successfully"}
    else:
        raise HTTPException(status_code=400, detail="Failed to unlink document")


@router.get("/characters/{character_id}/documents", response_model=List[KnowledgeDocumentResponse])
async def list_character_knowledge_documents(
        character_id: int,
        db: AsyncSession = Depends(get_db)
):
    """获取角色关联的所有知识库文档"""
    documents = await rag_service.get_character_knowledge_documents(db, character_id)
    return documents


@router.delete("/documents/{document_id}")
async def delete_knowledge_document(
        document_id: int,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """删除知识库文档（只能删除自己创建的）"""
    result = await db.execute(
        select(KnowledgeDocument).where(KnowledgeDocument.id == document_id)
    )
    document = result.scalar_one_or_none()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    # 检查权限
    if document.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="No permission to delete this document")

    # 删除文档（级联删除chunks，自动解除所有关联）
    await db.delete(document)
    await db.commit()

    return {"message": "Document deleted successfully"}

@router.put("/documents/{document_id}/visibility")
async def update_document_visibility(
        document_id: int,
        is_public: bool,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """更新知识库文档的公开状态"""

    document = await db.get(KnowledgeDocument, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    # 检查权限
    if document.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="No permission to update this document")

    document.is_public = is_public
    await db.commit()

    return {
        "id": document.id,
        "title": document.title,
        "is_public": document.is_public
    }