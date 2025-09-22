# app/api/knowledge.py
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
import shutil
from pathlib import Path

from ..database import get_db
from ..models import Character, User
from ..schemas import KnowledgeCreate, KnowledgeResponse
from ..services.rag_service import rag_service
from ..services.llm_service import LLMService
from .auth import get_current_user

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

# 临时文件存储目录
TEMP_UPLOAD_DIR = Path("temp_uploads")
TEMP_UPLOAD_DIR.mkdir(exist_ok=True)


@router.post("/{character_id}/upload")
async def upload_knowledge_files(
        character_id: int,
        files: List[UploadFile] = File(...),
        texts: Optional[List[str]] = Form(None),
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """为角色上传知识库文件"""
    # 验证角色存在
    result = await db.execute(
        select(Character).where(Character.id == character_id)
    )
    character = result.scalar_one_or_none()

    if not character:
        raise HTTPException(status_code=404, detail="Character not found")

    try:
        # 保存上传的文件到临时目录
        saved_files = []
        for file in files:
            if file.filename:
                file_path = TEMP_UPLOAD_DIR / f"{character_id}_{file.filename}"
                with open(file_path, "wb") as buffer:
                    shutil.copyfileobj(file.file, buffer)
                saved_files.append(str(file_path))

        # 处理文本输入
        text_list = []
        if texts:
            text_list = [t for t in texts if t.strip()]

        # 创建知识库
        success = await rag_service.create_character_knowledge_base(
            character_id=character_id,
            files=saved_files,
            texts=text_list
        )

        # 清理临时文件
        for file_path in saved_files:
            try:
                Path(file_path).unlink()
            except:
                pass

        if success:
            return {"message": "知识库创建成功", "character_id": character_id}
        else:
            raise HTTPException(status_code=500, detail="知识库创建失败")

    except Exception as e:
        # 清理临时文件
        for file_path in saved_files:
            try:
                Path(file_path).unlink()
            except:
                pass
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")


@router.post("/{character_id}/add-text")
async def add_text_knowledge(
        character_id: int,
        texts: List[str],
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """为角色添加文本知识"""
    # 验证角色存在
    result = await db.execute(
        select(Character).where(Character.id == character_id)
    )
    character = result.scalar_one_or_none()

    if not character:
        raise HTTPException(status_code=404, detail="Character not found")

    # 过滤空文本
    valid_texts = [t.strip() for t in texts if t.strip()]

    if not valid_texts:
        raise HTTPException(status_code=400, detail="没有有效的文本内容")

    # 更新知识库
    success = await rag_service.update_character_knowledge_base(
        character_id=character_id,
        texts=valid_texts
    )

    if success:
        return {"message": f"成功添加 {len(valid_texts)} 条知识", "character_id": character_id}
    else:
        raise HTTPException(status_code=500, detail="添加知识失败")


@router.get("/{character_id}/search")
async def search_knowledge(
        character_id: int,
        query: str,
        k: int = 5,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """搜索角色知识库"""
    # 验证角色存在
    result = await db.execute(
        select(Character).where(Character.id == character_id)
    )
    character = result.scalar_one_or_none()

    if not character:
        raise HTTPException(status_code=404, detail="Character not found")

    # 搜索知识
    knowledge_chunks = await rag_service.search_knowledge(
        character_id=character_id,
        query=query,
        k=k
    )

    return {
        "query": query,
        "character_id": character_id,
        "results": knowledge_chunks
    }


@router.get("/{character_id}/summary")
async def get_knowledge_summary(
        character_id: int,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """获取角色知识库摘要"""
    # 验证角色存在
    result = await db.execute(
        select(Character).where(Character.id == character_id)
    )
    character = result.scalar_one_or_none()

    if not character:
        raise HTTPException(status_code=404, detail="Character not found")

    # 获取知识样本（用于生成摘要）
    knowledge_chunks = await rag_service.search_knowledge(
        character_id=character_id,
        query=character.name,  # 使用角色名字作为查询
        k=10  # 获取更多内容用于摘要
    )

    if not knowledge_chunks:
        return {
            "character_id": character_id,
            "summary": "该角色暂无知识库内容"
        }

    # 生成摘要
    summary = await LLMService.generate_knowledge_summary(
        character_name=character.name,
        knowledge_chunks=knowledge_chunks
    )

    return {
        "character_id": character_id,
        "summary": summary,
        "knowledge_count": len(knowledge_chunks)
    }


@router.delete("/{character_id}")
async def delete_knowledge_base(
        character_id: int,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """删除角色知识库"""
    # 验证角色存在
    result = await db.execute(
        select(Character).where(Character.id == character_id)
    )
    character = result.scalar_one_or_none()

    if not character:
        raise HTTPException(status_code=404, detail="Character not found")

    # 删除知识库
    success = await rag_service.delete_character_knowledge_base(character_id)

    if success:
        return {"message": "知识库删除成功", "character_id": character_id}
    else:
        raise HTTPException(status_code=500, detail="知识库删除失败")


@router.get("/{character_id}/status")
async def get_knowledge_status(
        character_id: int,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """获取角色知识库状态"""
    # 验证角色存在
    result = await db.execute(
        select(Character).where(Character.id == character_id)
    )
    character = result.scalar_one_or_none()

    if not character:
        raise HTTPException(status_code=404, detail="Character not found")

    # 检查是否有知识库
    vectorstore = await rag_service.get_character_vectorstore(character_id)
    has_knowledge = vectorstore is not None

    # 如果有知识库，获取一些统计信息
    if has_knowledge:
        try:
            # 尝试搜索获取文档数量（通过搜索空字符串）
            sample_docs = await rag_service.search_knowledge(character_id, character.name, k=1)
            return {
                "character_id": character_id,
                "has_knowledge": True,
                "sample_available": len(sample_docs) > 0
            }
        except:
            return {
                "character_id": character_id,
                "has_knowledge": True,
                "sample_available": False
            }
    else:
        return {
            "character_id": character_id,
            "has_knowledge": False
        }