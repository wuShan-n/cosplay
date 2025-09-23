from typing import List, Optional, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.schema import Document
from langchain_community.document_loaders import PyPDFLoader, TextLoader, Docx2txtLoader
import dashscope
from dashscope import TextEmbedding
import tempfile
import os
import aiofiles
from ..models import KnowledgeDocument, KnowledgeChunk, Character
from ..config import settings

# 使用通义千问的嵌入模型
dashscope.api_key = settings.DASHSCOPE_API_KEY


class RAGService:
    def __init__(self):
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=50,
            separators=["\n\n", "\n", "。", "！", "？", ".", "!", "?", " ", ""]
        )

    async def create_embedding(self, text: str) -> List[float]:
        """使用通义千问创建文本嵌入"""
        response = TextEmbedding.call(
            model=TextEmbedding.Models.text_embedding_v2,
            input=text
        )
        if response.status_code == 200:
            return response.output['embeddings'][0]['embedding']
        else:
            raise Exception(f"Embedding failed: {response}")

    async def process_document(
            self,
            db: AsyncSession,
            character_id: int,
            file_content: bytes,
            filename: str,
            source_url: str
    ) -> KnowledgeDocument:
        """处理上传的文档并生成向量嵌入"""

        # 确定文档类型
        file_ext = filename.lower().split('.')[-1]
        source_type = file_ext if file_ext in ['pdf', 'txt', 'docx'] else 'txt'

        # 保存临时文件并加载
        with tempfile.NamedTemporaryFile(suffix=f'.{file_ext}', delete=False) as tmp_file:
            tmp_file.write(file_content)
            tmp_path = tmp_file.name

        try:
            # 根据文件类型选择加载器
            if file_ext == 'pdf':
                loader = PyPDFLoader(tmp_path)
            elif file_ext == 'docx':
                loader = Docx2txtLoader(tmp_path)
            else:
                loader = TextLoader(tmp_path, encoding='utf-8')

            documents = loader.load()

            # 分割文档
            chunks = self.text_splitter.split_documents(documents)

            # 创建文档记录
            knowledge_doc = KnowledgeDocument(
                character_id=character_id,
                title=filename,
                source_type=source_type,
                source_url=source_url
            )
            db.add(knowledge_doc)
            await db.flush()  # 获取ID但不提交

            # 创建chunk记录和嵌入
            for i, chunk in enumerate(chunks):
                # 生成嵌入向量
                embedding = await self.create_embedding(chunk.page_content)

                # 创建chunk记录
                knowledge_chunk = KnowledgeChunk(
                    document_id=knowledge_doc.id,
                    content=chunk.page_content,
                    chunk_metadata=chunk.metadata,  # 使用 chunk_metadata
                    embedding=embedding,
                    chunk_index=i
                )
                db.add(knowledge_chunk)

            await db.commit()
            await db.refresh(knowledge_doc)

            return knowledge_doc

        finally:
            os.unlink(tmp_path)

    async def add_manual_knowledge(
            self,
            db: AsyncSession,
            character_id: int,
            title: str,
            content: str
    ) -> KnowledgeDocument:
        """手动添加知识内容"""

        # 创建文档记录
        knowledge_doc = KnowledgeDocument(
            character_id=character_id,
            title=title,
            source_type='manual',
            source_url=None
        )
        db.add(knowledge_doc)
        await db.flush()

        # 分割内容
        chunks = self.text_splitter.split_text(content)

        # 创建chunk记录
        for i, chunk_text in enumerate(chunks):
            embedding = await self.create_embedding(chunk_text)

            knowledge_chunk = KnowledgeChunk(
                document_id=knowledge_doc.id,
                content=chunk_text,
                chunk_metadata={'source': 'manual'},  # 使用 chunk_metadata
                embedding=embedding,
                chunk_index=i
            )
            db.add(knowledge_chunk)

        await db.commit()
        await db.refresh(knowledge_doc)

        return knowledge_doc

    async def search_knowledge(
            self,
            db: AsyncSession,
            character_id: int,
            query: str,
            k: int = 3
    ) -> List[Dict]:
        """检索相关知识"""

        # 获取查询向量
        query_embedding = await self.create_embedding(query)

        stmt = (
            select(
                KnowledgeChunk.content,
                KnowledgeChunk.chunk_metadata,
                KnowledgeDocument.title.label("doc_title"),
                KnowledgeChunk.embedding.l2_distance(query_embedding).label("distance")
            )
            .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
            .where(KnowledgeDocument.character_id == character_id)
            .order_by(KnowledgeChunk.embedding.l2_distance(query_embedding))
            .limit(k)
        )

        result = await db.execute(stmt)


        chunks = []
        for row in result:
            chunks.append({
                "content": row.content,
                "metadata": row.chunk_metadata,  # 返回时仍使用 metadata 作为键名
                "doc_title": row.doc_title,
                "relevance_score": 1 - row.distance  # 转换为相似度分数
            })

        return chunks

    async def build_context_prompt(
            self,
            retrieved_chunks: List[Dict]
    ) -> str:
        """构建RAG上下文提示"""
        if not retrieved_chunks:
            return ""

        context_parts = ["以下是相关的背景知识，请参考这些信息来回答：\n"]

        for i, chunk in enumerate(retrieved_chunks, 1):
            context_parts.append(
                f"[知识{i} - 来自《{chunk['doc_title']}》]\n{chunk['content']}\n"
            )

        context_parts.append("\n请基于上述知识，结合角色设定来回答用户的问题。")

        return "\n".join(context_parts)


# 创建单例实例
rag_service = RAGService()