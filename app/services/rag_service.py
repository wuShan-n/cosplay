from typing import List, Optional, Dict, Set
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text, and_
from sqlalchemy.orm import joinedload, selectinload
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import PyPDFLoader, TextLoader, Docx2txtLoader
import dashscope
from dashscope import TextEmbedding
import tempfile
import os
from ..models import KnowledgeDocument, KnowledgeChunk, Character, User
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

    async def create_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """批量创建嵌入，提高效率"""
        embeddings = []
        uncached_texts = []
        uncached_indices = []

        for i, text in enumerate(texts):
            embeddings.append(None)
            uncached_texts.append(text)
            uncached_indices.append(i)

        # 批量处理文本
        if uncached_texts:
            # 通义千问支持批量嵌入
            response = TextEmbedding.call(
                model=TextEmbedding.Models.text_embedding_v2,
                input=uncached_texts
            )
            if response.status_code == 200:
                for i, embedding_data in enumerate(response.output['embeddings']):
                    embedding = embedding_data['embedding']
                    idx = uncached_indices[i]
                    embeddings[idx] = embedding
            else:
                raise Exception(f"Batch embedding failed: {response}")

        return embeddings

    async def process_document(
            self,
            db: AsyncSession,
            file_content: bytes,
            filename: str,
            source_url: str,
            user_id: Optional[int] = None,
            description: Optional[str] = None,
            is_public: Optional[bool] = None
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
                title=filename,
                description=description,
                source_type=source_type,
                source_url=source_url,
                created_by=user_id,
                is_public=is_public
            )
            db.add(knowledge_doc)
            await db.flush()  # 获取ID但不提交

            # 批量生成嵌入向量
            chunk_texts = [chunk.page_content for chunk in chunks]
            embeddings = await self.create_embeddings_batch(chunk_texts)

            # 批量创建chunk记录
            chunk_objects = []
            for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                knowledge_chunk = KnowledgeChunk(
                    document_id=knowledge_doc.id,
                    content=chunk.page_content,
                    chunk_metadata=chunk.metadata,
                    embedding=embedding,
                    chunk_index=i
                )
                chunk_objects.append(knowledge_chunk)

            # 批量添加
            db.add_all(chunk_objects)
            await db.commit()
            await db.refresh(knowledge_doc)

            return knowledge_doc

        finally:
            os.unlink(tmp_path)

    async def link_knowledge_to_character(
            self,
            db: AsyncSession,
            character_id: int,
            document_id: int
    ) -> bool:
        """将知识库关联到角色"""
        # 获取角色和文档
        character = await db.get(Character, character_id)
        document = await db.get(KnowledgeDocument, document_id)

        if not character or not document:
            return False

        # 检查是否已经关联
        if document not in character.knowledge_documents:
            character.knowledge_documents.append(document)
            character.use_knowledge_base = True  # 自动启用知识库
            await db.commit()

        return True

    async def unlink_knowledge_from_character(
            self,
            db: AsyncSession,
            character_id: int,
            document_id: int
    ) -> bool:
        """解除知识库与角色的关联"""
        character = await db.get(Character, character_id)
        document = await db.get(KnowledgeDocument, document_id)

        if not character or not document:
            return False

        if document in character.knowledge_documents:
            character.knowledge_documents.remove(document)

            # 如果没有知识库了，自动禁用
            if not character.knowledge_documents:
                character.use_knowledge_base = False

            await db.commit()

        return True

    async def search_knowledge(
            self,
            db: AsyncSession,
            character_id: int,
            query: str,
            k: int = 3
    ) -> List[Dict]:
        """检索相关知识，优化版本"""

        # 获取角色关联的所有知识库文档ID
        character = await db.get(Character, character_id, options=[selectinload(Character.knowledge_documents)])
        if not character or not character.knowledge_documents:
            return []

        document_ids = [doc.id for doc in character.knowledge_documents]

        # 获取查询向量
        query_embedding = await self.create_embedding(query)

        # 使用优化的查询，只搜索关联的文档
        stmt = (
            select(
                KnowledgeChunk.content,
                KnowledgeChunk.chunk_metadata,
                KnowledgeDocument.title.label("doc_title"),
                KnowledgeDocument.description.label("doc_description"),
                KnowledgeChunk.embedding.l2_distance(query_embedding).label("distance")
            )
            .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
            .where(KnowledgeDocument.id.in_(document_ids))
            .order_by(KnowledgeChunk.embedding.l2_distance(query_embedding))
            .limit(k)
        )

        result = await db.execute(stmt)

        chunks = []
        for row in result:
            chunks.append({
                "content": row.content,
                "metadata": row.chunk_metadata,
                "doc_title": row.doc_title,
                "doc_description": row.doc_description,
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
            doc_info = f"《{chunk['doc_title']}》"
            if chunk.get('doc_description'):
                doc_info += f" - {chunk['doc_description']}"

            context_parts.append(
                f"[知识{i} - 来自{doc_info}]\n{chunk['content']}\n"
            )

        context_parts.append("\n请基于上述知识，结合角色设定来回答用户的问题。")

        return "\n".join(context_parts)

    async def get_public_knowledge_documents(
            self,
            db: AsyncSession,
            skip: int = 0,
            limit: int = 20
    ) -> List[KnowledgeDocument]:
        """获取公开的知识库列表"""
        result = await db.execute(
            select(KnowledgeDocument)
            .where(KnowledgeDocument.is_public == True)
            .order_by(KnowledgeDocument.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return result.scalars().all()

    async def get_character_knowledge_documents(
            self,
            db: AsyncSession,
            character_id: int
    ) -> List[KnowledgeDocument]:
        """获取角色关联的所有知识库"""
        character = await db.get(
            Character,
            character_id,
            options=[selectinload(Character.knowledge_documents)]
        )
        if not character:
            return []
        return character.knowledge_documents

    def clear_embedding_cache(self):
        """清空嵌入缓存"""
        self._embedding_cache.clear()


# 创建单例实例
rag_service = RAGService()