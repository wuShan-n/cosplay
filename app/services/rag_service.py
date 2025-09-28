from typing import List, Optional, Dict, Any, Coroutine, Sequence
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, Row, RowMapping
from sqlalchemy.orm import selectinload, joinedload, subqueryload
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import PyPDFLoader, TextLoader, Docx2txtLoader
import dashscope
from dashscope import TextEmbedding
import tempfile
import os
import asyncio
import logging
import time
from ..models import KnowledgeDocument, KnowledgeChunk, Character
from ..config import settings

# 配置日志
logger = logging.getLogger(__name__)

# 使用通义千问的嵌入模型
dashscope.api_key = settings.DASHSCOPE_API_KEY


class RAGService:
    def __init__(self):
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=50,
            separators=["\n\n", "\n", "。", "！", "？", ".", "!", "?", " ", ""]
        )
        # 批处理配置
        self.BATCH_SIZE = 25  # API批量限制
        self.MAX_RETRIES = 3  # 最大重试次数

    async def create_embedding(self, text: str) -> List[float]:
        """创建单个文本嵌入"""
        try:
            response = TextEmbedding.call(
                model=TextEmbedding.Models.text_embedding_v2,
                input=text
            )
            if response.status_code == 200:
                return response.output['embeddings'][0]['embedding']
            else:
                raise Exception(f"Embedding failed: {response.message}")
        except Exception as e:
            logger.error(f"Failed to create embedding: {str(e)}")
            raise

    async def create_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """批量创建嵌入，支持自动重试"""
        if not texts:
            return []

        embeddings = []

        # 分批处理
        for i in range(0, len(texts), self.BATCH_SIZE):
            batch = texts[i:i + self.BATCH_SIZE]

            # 重试逻辑
            for attempt in range(self.MAX_RETRIES):
                try:
                    response = TextEmbedding.call(
                        model=TextEmbedding.Models.text_embedding_v2,
                        input=batch
                    )

                    if response.status_code == 200:
                        batch_embeddings = [item['embedding'] for item in response.output['embeddings']]
                        embeddings.extend(batch_embeddings)
                        break
                    else:
                        logger.warning(f"Batch embedding failed (attempt {attempt + 1}): {response.message}")
                        if attempt < self.MAX_RETRIES - 1:
                            await asyncio.sleep(2 ** attempt)  # 指数退避
                        else:
                            raise Exception(f"Failed after {self.MAX_RETRIES} attempts")

                except Exception as e:
                    logger.error(f"Batch embedding error (attempt {attempt + 1}): {str(e)}")
                    if attempt < self.MAX_RETRIES - 1:
                        await asyncio.sleep(2 ** attempt)
                    else:
                        raise

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
        """优化的文档处理：简化流程，提高效率"""

        logger.info(f"Starting to process document: {filename}")

        # 1. 创建文档记录
        file_ext = filename.lower().split('.')[-1]
        source_type = file_ext if file_ext in ['pdf', 'txt', 'docx'] else 'txt'

        knowledge_doc = KnowledgeDocument(
            title=filename,
            description=description,
            source_type=source_type,
            source_url=source_url,
            created_by=user_id,
            is_public=is_public if is_public is not None else False
        )
        db.add(knowledge_doc)
        await db.flush()  # 获取ID但暂不提交

        # 2. 加载和分割文档
        try:
            chunks_data = await self._load_and_split_document(file_content, file_ext)
            logger.info(f"Document split into {len(chunks_data)} chunks")

            # 3. 批量生成嵌入并保存
            await self._process_chunks_batch(db, knowledge_doc.id, chunks_data)

            # 4. 提交事务
            await db.commit()
            await db.refresh(knowledge_doc)

            logger.info(f"Document processed successfully: {knowledge_doc.id}")
            return knowledge_doc

        except Exception as e:
            logger.error(f"Document processing failed: {str(e)}")
            await db.rollback()
            raise

    async def _load_and_split_document(self, file_content: bytes, file_ext: str) -> List[Dict]:
        """加载并分割文档，返回文本块数据"""
        # 创建临时文件
        with tempfile.NamedTemporaryFile(suffix=f'.{file_ext}', delete=False) as tmp_file:
            tmp_file.write(file_content)
            tmp_path = tmp_file.name

        try:
            # 选择合适的加载器
            if file_ext == 'pdf':
                loader = PyPDFLoader(tmp_path)
            elif file_ext == 'docx':
                loader = Docx2txtLoader(tmp_path)
            else:
                loader = TextLoader(tmp_path, encoding='utf-8')

            # 加载文档
            documents = loader.load()

            # 一次性分割所有文档
            all_splits = self.text_splitter.split_documents(documents)

            # 使用列表推导式高效生成数据
            chunks_data = [{
                "content": chunk.page_content,
                "metadata": chunk.metadata,
                "index": idx
            } for idx, chunk in enumerate(all_splits)]

            return chunks_data

        finally:
            # 清理临时文件
            try:
                os.unlink(tmp_path)
            except:
                pass

    async def _process_chunks_batch(self, db: AsyncSession, document_id: int, chunks_data: List[Dict]):
        """批量处理文本块：生成嵌入并保存"""
        total_chunks = len(chunks_data)

        # 按批次处理
        for batch_start in range(0, total_chunks, self.BATCH_SIZE):
            batch_end = min(batch_start + self.BATCH_SIZE, total_chunks)
            batch = chunks_data[batch_start:batch_end]

            # 提取文本
            texts = [chunk["content"] for chunk in batch]

            # 生成嵌入
            logger.info(f"Generating embeddings for chunks {batch_start + 1}-{batch_end}/{total_chunks}")
            embeddings = await self.create_embeddings_batch(texts)

            # 创建并保存知识块
            for chunk_data, embedding in zip(batch, embeddings):
                knowledge_chunk = KnowledgeChunk(
                    document_id=document_id,
                    content=chunk_data["content"],
                    chunk_metadata=chunk_data["metadata"],
                    embedding=embedding,
                    chunk_index=chunk_data["index"]
                )
                db.add(knowledge_chunk)

            # 定期刷新，避免内存占用过多
            await db.flush()
            logger.info(f"Saved chunks {batch_start + 1}-{batch_end}")



    async def search_knowledge(
            self,
            db: AsyncSession,
            character_id: int,
            query: str,
            k: int = 3
    ) -> List[Dict]:
        """检索相关知识 - 使用异步查询"""
        # 使用异步查询获取角色及其知识库
        result = await db.execute(
            select(Character)
            .where(Character.id == character_id)
            .options(selectinload(Character.knowledge_documents))
        )
        character = result.scalar_one_or_none()

        if not character or not character.knowledge_documents:
            return []
        document_ids = [doc.id for doc in character.knowledge_documents]

        # 步骤 2: 生成查询向量
        query_embedding = await self.create_embedding(query)

        # 步骤 3: 构建并执行优化的向量搜索查询

        # pgvector 的余弦距离操作符 '<=>'，距离越小表示越相似
        distance_op = KnowledgeChunk.embedding.cosine_distance(query_embedding)

        # 子查询: 仅对 KnowledgeChunk 表进行操作，快速利用索引找出最相似的 k 个块
        subquery = (
            select(
                KnowledgeChunk.id.label("chunk_id"),
                distance_op.label("distance")
            )
            .where(KnowledgeChunk.document_id.in_(document_ids))
            .order_by(distance_op)
            .limit(k)
            .subquery('nearest_chunks')
        )

        # 主查询: 将子查询的结果与父表进行JOIN，获取完整的 chunk 内容和文档元数据
        stmt = (
            select(
                KnowledgeChunk.content,
                KnowledgeChunk.chunk_metadata,
                KnowledgeDocument.title.label("doc_title"),
                KnowledgeDocument.description.label("doc_description"),
                subquery.c.distance
            )
            .join(subquery, KnowledgeChunk.id == subquery.c.chunk_id)
            .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
            .order_by(subquery.c.distance)  # 保证最终输出的顺序
        )

        result = await db.execute(stmt)

        # 步骤 4: 组装并返回结果
        chunks = []
        for row in result.mappings():
            # 将余弦距离 (0 到 2) 转换为更直观的相似度分数 (通常在 0 到 1 之间)
            # 1 - distance 是一个简单且有效的转换方式
            relevance_score = 1 - row.distance
            chunks.append({
                "content": row.content,
                "metadata": row.chunk_metadata,
                "doc_title": row.doc_title,
                "doc_description": row.doc_description,
                "relevance_score": relevance_score
            })

        return chunks

    async def build_context_prompt(self, retrieved_chunks: List[Dict]) -> str:
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


# 创建单例实例
rag_service = RAGService()