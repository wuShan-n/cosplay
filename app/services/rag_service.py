from typing import List, Optional, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from sqlalchemy.orm import selectinload
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import PyPDFLoader, TextLoader, Docx2txtLoader
import dashscope
from dashscope import TextEmbedding
import tempfile
import os
import asyncio
import logging
import time
import sys
from ..models import KnowledgeDocument, KnowledgeChunk, Character, User
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
        # 最大批量大小（根据API限制设置）
        self.MAX_BATCH_SIZE = 25
        # 重试次数
        self.MAX_RETRIES = 3

    def _print_progress(self, message: str, level: str = "INFO"):
        """打印进度信息"""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        level_color = {
            "INFO": "\033[94m",  # 蓝色
            "SUCCESS": "\033[92m",  # 绿色
            "WARNING": "\033[93m",  # 黄色
            "ERROR": "\033[91m",  # 红色
            "DEBUG": "\033[90m"  # 灰色
        }
        reset_color = "\033[0m"

        color = level_color.get(level, "\033[94m")
        print(f"{color}[{timestamp}] {level}: {message}{reset_color}")
        sys.stdout.flush()

    async def create_embedding(self, text: str) -> List[float]:
        """使用通义千问创建文本嵌入"""
        try:
            self._print_progress(f"创建单个文本嵌入，长度: {len(text)} 字符", "DEBUG")
            response = TextEmbedding.call(
                model=TextEmbedding.Models.text_embedding_v2,
                input=text
            )
            if response.status_code == 200:
                self._print_progress("单个文本嵌入创建成功", "SUCCESS")
                return response.output['embeddings'][0]['embedding']
            else:
                raise Exception(f"Embedding failed: {response}")
        except Exception as e:
            self._print_progress(f"嵌入创建失败: {str(e)}", "ERROR")
            logger.error(f"Embedding creation failed: {str(e)}")
            raise

    async def create_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """批量创建嵌入，自动分批处理"""
        if not texts:
            return []

        total_batches = (len(texts) + self.MAX_BATCH_SIZE - 1) // self.MAX_BATCH_SIZE
        self._print_progress(f"开始批量嵌入处理，共 {len(texts)} 个文本，需要 {total_batches} 个批次", "INFO")

        # 分批处理
        embeddings = []
        for batch_num in range(0, len(texts), self.MAX_BATCH_SIZE):
            batch = texts[batch_num:batch_num + self.MAX_BATCH_SIZE]
            current_batch = (batch_num // self.MAX_BATCH_SIZE) + 1
            self._print_progress(f"处理批次 {current_batch}/{total_batches}，本批 {len(batch)} 个文本", "INFO")

            retries = 0
            success = False

            while retries < self.MAX_RETRIES and not success:
                try:
                    self._print_progress(f"调用嵌入API (尝试 {retries + 1}/{self.MAX_RETRIES})", "DEBUG")
                    response = TextEmbedding.call(
                        model=TextEmbedding.Models.text_embedding_v2,
                        input=batch
                    )

                    if response.status_code == 200:
                        batch_embeddings = [item['embedding'] for item in response.output['embeddings']]
                        embeddings.extend(batch_embeddings)
                        success = True
                        self._print_progress(f"批次 {current_batch} 嵌入创建成功", "SUCCESS")
                    else:
                        self._print_progress(f"批次嵌入失败 (尝试 {retries + 1}): {response}", "WARNING")
                        retries += 1
                        if retries < self.MAX_RETRIES:
                            wait_time = 2 ** retries
                            self._print_progress(f"等待 {wait_time} 秒后重试", "DEBUG")
                            await asyncio.sleep(wait_time)
                except Exception as e:
                    self._print_progress(f"批次嵌入错误: {str(e)}", "ERROR")
                    retries += 1
                    if retries < self.MAX_RETRIES:
                        wait_time = 2 ** retries
                        self._print_progress(f"等待 {wait_time} 秒后重试", "DEBUG")
                        await asyncio.sleep(wait_time)

            if not success:
                error_msg = f"批次 {current_batch} 在 {self.MAX_RETRIES} 次尝试后仍失败"
                self._print_progress(error_msg, "ERROR")
                raise Exception(error_msg)

        self._print_progress(f"批量嵌入处理完成，共生成 {len(embeddings)} 个嵌入向量", "SUCCESS")
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
        """流式处理上传的文档：分析一部分，上传一部分"""

        start_time = time.time()
        self._print_progress(f"开始流式处理文档: {filename} ({len(file_content)} 字节)", "INFO")

        # 确定文档类型
        file_ext = filename.lower().split('.')[-1]
        source_type = file_ext if file_ext in ['pdf', 'txt', 'docx'] else 'txt'
        self._print_progress(f"检测到文档类型: {file_ext}", "DEBUG")

        # 创建文档记录
        self._print_progress("创建知识文档记录...", "INFO")
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
        self._print_progress(f"知识文档记录创建成功，ID: {knowledge_doc.id}", "SUCCESS")

        # 保存临时文件并加载
        with tempfile.NamedTemporaryFile(suffix=f'.{file_ext}', delete=False) as tmp_file:
            tmp_file.write(file_content)
            tmp_path = tmp_file.name
        self._print_progress(f"创建临时文件: {tmp_path}", "DEBUG")

        try:
            # 根据文件类型选择加载器
            self._print_progress("加载文档内容...", "INFO")
            if file_ext == 'pdf':
                loader = PyPDFLoader(tmp_path)
            elif file_ext == 'docx':
                loader = Docx2txtLoader(tmp_path)
            else:
                # 统一使用 UTF-8 编码
                loader = TextLoader(tmp_path, encoding='utf-8')

            documents = loader.load()
            self._print_progress(f"文档加载完成，共 {len(documents)} 页/段落", "SUCCESS")

            # 初始化计数器
            total_chunks = 0
            saved_chunks = 0
            chunk_objects = []
            chunk_texts = []

            # 流式处理每个文档部分
            for doc_index, document in enumerate(documents):
                self._print_progress(f"处理第 {doc_index + 1}/{len(documents)} 部分", "INFO")

                # 分割当前部分
                chunks = self.text_splitter.split_documents([document])
                self._print_progress(f"当前部分分割为 {len(chunks)} 个文本块", "DEBUG")

                # 收集文本块
                for chunk in chunks:
                    chunk_texts.append(chunk.page_content)
                    chunk_objects.append({
                        "content": chunk.page_content,
                        "metadata": chunk.metadata,
                        "index": total_chunks
                    })
                    total_chunks += 1

                    # 当收集到足够批量或处理完最后一部分时，生成嵌入并保存
                    if len(chunk_texts) >= self.MAX_BATCH_SIZE or doc_index == len(documents) - 1:
                        # 生成嵌入向量
                        self._print_progress(f"为 {len(chunk_texts)} 个文本块生成嵌入向量", "INFO")
                        embeddings = await self.create_embeddings_batch(chunk_texts)

                        # 创建并保存知识块
                        for i, (chunk_data, embedding) in enumerate(zip(chunk_objects, embeddings)):
                            knowledge_chunk = KnowledgeChunk(
                                document_id=knowledge_doc.id,
                                content=chunk_data["content"],
                                chunk_metadata=chunk_data["metadata"],
                                embedding=embedding,
                                chunk_index=chunk_data["index"]
                            )
                            db.add(knowledge_chunk)

                        # 提交当前批次
                        await db.flush()
                        saved_chunks += len(chunk_objects)
                        self._print_progress(f"已保存 {saved_chunks}/{total_chunks} 个文本块", "INFO")

                        # 重置临时存储
                        chunk_texts = []
                        chunk_objects = []

            await db.commit()
            await db.refresh(knowledge_doc)

            # 计算处理时间
            processing_time = time.time() - start_time
            self._print_progress(f"文档处理完成！总耗时: {processing_time:.2f} 秒", "SUCCESS")
            self._print_progress(f"文档ID: {knowledge_doc.id}, 文本块数量: {total_chunks}", "INFO")

            return knowledge_doc

        except Exception as e:
            self._print_progress(f"文档处理失败: {str(e)}", "ERROR")
            logger.error(f"Document processing failed: {str(e)}")
            await db.rollback()
            raise
        finally:
            try:
                os.unlink(tmp_path)
                self._print_progress("临时文件已清理", "DEBUG")
            except Exception as e:
                self._print_progress(f"清理临时文件失败: {str(e)}", "WARNING")

    async def link_knowledge_to_character(
            self,
            db: AsyncSession,
            character_id: int,
            document_id: int
    ) -> bool:
        """将知识库关联到角色"""
        self._print_progress(f"关联知识文档 {document_id} 到角色 {character_id}", "INFO")

        # 获取角色和文档
        character = await db.get(Character, character_id)
        document = await db.get(KnowledgeDocument, document_id)

        if not character or not document:
            self._print_progress("角色或文档不存在", "ERROR")
            return False

        # 检查是否已经关联
        if document not in character.knowledge_documents:
            character.knowledge_documents.append(document)
            character.use_knowledge_base = True  # 自动启用知识库
            await db.commit()
            self._print_progress("知识库关联成功", "SUCCESS")
            return True
        else:
            self._print_progress("知识库已关联，无需重复操作", "WARNING")
            return True

    async def unlink_knowledge_from_character(
            self,
            db: AsyncSession,
            character_id: int,
            document_id: int
    ) -> bool:
        """解除知识库与角色的关联"""
        self._print_progress(f"解除知识文档 {document_id} 与角色 {character_id} 的关联", "INFO")

        character = await db.get(Character, character_id)
        document = await db.get(KnowledgeDocument, document_id)

        if not character or not document:
            self._print_progress("角色或文档不存在", "ERROR")
            return False

        if document in character.knowledge_documents:
            character.knowledge_documents.remove(document)

            # 如果没有知识库了，自动禁用
            if not character.knowledge_documents:
                character.use_knowledge_base = False

            await db.commit()
            self._print_progress("知识库关联已解除", "SUCCESS")
            return True

        self._print_progress("知识库未关联，无需操作", "WARNING")
        return True

    async def search_knowledge(
            self,
            db: AsyncSession,
            character_id: int,
            query: str,
            k: int = 3
    ) -> List[Dict]:
        """检索相关知识，优化版本"""
        self._print_progress(f"为角色 {character_id} 检索知识: {query[:50]}...", "INFO")

        # 获取角色关联的所有知识库文档ID
        character = await db.get(Character, character_id, options=[selectinload(Character.knowledge_documents)])
        if not character or not character.knowledge_documents:
            self._print_progress("角色不存在或未关联知识库", "WARNING")
            return []

        document_ids = [doc.id for doc in character.knowledge_documents]
        self._print_progress(f"在 {len(document_ids)} 个文档中检索", "DEBUG")

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

        self._print_progress(f"检索完成，找到 {len(chunks)} 个相关片段", "SUCCESS")
        return chunks

    async def build_context_prompt(
            self,
            retrieved_chunks: List[Dict]
    ) -> str:
        """构建RAG上下文提示"""
        if not retrieved_chunks:
            self._print_progress("无检索结果，使用空上下文", "DEBUG")
            return ""

        self._print_progress(f"构建上下文提示，使用 {len(retrieved_chunks)} 个片段", "INFO")

        context_parts = ["以下是相关的背景知识，请参考这些信息来回答：\n"]

        for i, chunk in enumerate(retrieved_chunks, 1):
            doc_info = f"《{chunk['doc_title']}》"
            if chunk.get('doc_description'):
                doc_info += f" - {chunk['doc_description']}"

            context_parts.append(
                f"[知识{i} - 来自{doc_info}]\n{chunk['content']}\n"
            )

        context_parts.append("\n请基于上述知识，结合角色设定来回答用户的问题。")

        result = "\n".join(context_parts)
        self._print_progress(f"上下文构建完成，长度: {len(result)} 字符", "DEBUG")
        return result

    async def get_public_knowledge_documents(
            self,
            db: AsyncSession,
            skip: int = 0,
            limit: int = 20
    ) -> List[KnowledgeDocument]:
        """获取公开的知识库列表"""
        self._print_progress(f"获取公开知识库列表，skip: {skip}, limit: {limit}", "DEBUG")

        result = await db.execute(
            select(KnowledgeDocument)
            .where(KnowledgeDocument.is_public == True)
            .order_by(KnowledgeDocument.created_at.desc())
            .offset(skip)
            .limit(limit)
        )

        documents = result.scalars().all()
        self._print_progress(f"获取到 {len(documents)} 个公开文档", "DEBUG")
        return documents

    async def get_character_knowledge_documents(
            self,
            db: AsyncSession,
            character_id: int
    ) -> List[KnowledgeDocument]:
        """获取角色关联的所有知识库"""
        self._print_progress(f"获取角色 {character_id} 关联的知识库", "DEBUG")

        character = await db.get(
            Character,
            character_id,
            options=[selectinload(Character.knowledge_documents)]
        )
        if not character:
            self._print_progress("角色不存在", "WARNING")
            return []

        documents = character.knowledge_documents
        self._print_progress(f"角色关联了 {len(documents)} 个知识库", "DEBUG")
        return documents

    def clear_embedding_cache(self):
        """清空嵌入缓存"""
        self._print_progress("清空嵌入缓存", "INFO")
        self._embedding_cache.clear()


# 创建单例实例
rag_service = RAGService()