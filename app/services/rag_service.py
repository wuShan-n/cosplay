# app/services/rag_service.py
import os
import hashlib
from typing import List, Optional
from pathlib import Path

from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.vectorstores import Chroma
from langchain.embeddings import HuggingFaceEmbeddings
from langchain.document_loaders import (
    TextLoader, PDFLoader, DirectoryLoader,
    UnstructuredMarkdownLoader, JSONLoader
)
from langchain.schema import Document
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..models import Character
from ..config import settings


class RAGService:
    def __init__(self):
        # 使用轻量级的中文embedding模型
        self.embeddings = HuggingFaceEmbeddings(
            model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
            model_kwargs={'device': 'cpu'}
        )

        # 知识库存储路径
        self.knowledge_base_dir = Path("knowledge_bases")
        self.knowledge_base_dir.mkdir(exist_ok=True)

        # 向量数据库存储路径
        self.vector_db_dir = Path("vector_dbs")
        self.vector_db_dir.mkdir(exist_ok=True)

        # 文本分割器
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=50,
            separators=["\n\n", "\n", "。", "！", "？", "；", ".", "!", "?", ";"]
        )

        # 缓存已加载的向量数据库
        self._vector_stores = {}

    async def create_character_knowledge_base(
            self,
            character_id: int,
            files: List[str] = None,
            texts: List[str] = None
    ) -> bool:
        """为角色创建知识库"""
        try:
            character_kb_dir = self.knowledge_base_dir / str(character_id)
            character_kb_dir.mkdir(exist_ok=True)

            documents = []

            # 处理上传的文件
            if files:
                for file_path in files:
                    docs = await self._load_documents_from_file(file_path)
                    documents.extend(docs)

            # 处理直接输入的文本
            if texts:
                for i, text in enumerate(texts):
                    doc = Document(
                        page_content=text,
                        metadata={"source": f"text_input_{i}", "character_id": character_id}
                    )
                    documents.append(doc)

            if not documents:
                return False

            # 分割文档
            split_docs = self.text_splitter.split_documents(documents)

            # 创建向量数据库
            vector_db_path = str(self.vector_db_dir / str(character_id))
            vectorstore = Chroma.from_documents(
                documents=split_docs,
                embedding=self.embeddings,
                persist_directory=vector_db_path
            )
            vectorstore.persist()

            # 缓存向量数据库
            self._vector_stores[character_id] = vectorstore

            return True

        except Exception as e:
            print(f"创建知识库失败: {e}")
            return False

    async def _load_documents_from_file(self, file_path: str) -> List[Document]:
        """从文件加载文档"""
        file_path = Path(file_path)

        if not file_path.exists():
            return []

        try:
            if file_path.suffix.lower() == '.pdf':
                loader = PDFLoader(str(file_path))
            elif file_path.suffix.lower() == '.md':
                loader = UnstructuredMarkdownLoader(str(file_path))
            elif file_path.suffix.lower() == '.json':
                loader = JSONLoader(str(file_path), jq_schema='.[]', text_content=False)
            else:  # 默认作为文本文件处理
                loader = TextLoader(str(file_path), encoding='utf-8')

            return loader.load()

        except Exception as e:
            print(f"加载文件失败 {file_path}: {e}")
            return []

    async def get_character_vectorstore(self, character_id: int) -> Optional[Chroma]:
        """获取角色的向量数据库"""
        # 先从缓存中获取
        if character_id in self._vector_stores:
            return self._vector_stores[character_id]

        # 检查是否存在持久化的向量数据库
        vector_db_path = self.vector_db_dir / str(character_id)
        if vector_db_path.exists():
            try:
                vectorstore = Chroma(
                    persist_directory=str(vector_db_path),
                    embedding_function=self.embeddings
                )
                self._vector_stores[character_id] = vectorstore
                return vectorstore
            except Exception as e:
                print(f"加载向量数据库失败 {character_id}: {e}")

        return None

    async def search_knowledge(
            self,
            character_id: int,
            query: str,
            k: int = 3
    ) -> List[str]:
        """在角色知识库中搜索相关信息"""
        vectorstore = await self.get_character_vectorstore(character_id)

        if not vectorstore:
            return []

        try:
            # 相似性搜索
            docs = vectorstore.similarity_search(query, k=k)
            return [doc.page_content for doc in docs]
        except Exception as e:
            print(f"知识搜索失败: {e}")
            return []

    async def delete_character_knowledge_base(self, character_id: int) -> bool:
        """删除角色知识库"""
        try:
            # 从缓存中移除
            if character_id in self._vector_stores:
                del self._vector_stores[character_id]

            # 删除向量数据库文件
            vector_db_path = self.vector_db_dir / str(character_id)
            if vector_db_path.exists():
                import shutil
                shutil.rmtree(vector_db_path)

            # 删除知识库文件夹
            kb_path = self.knowledge_base_dir / str(character_id)
            if kb_path.exists():
                import shutil
                shutil.rmtree(kb_path)

            return True

        except Exception as e:
            print(f"删除知识库失败: {e}")
            return False

    async def update_character_knowledge_base(
            self,
            character_id: int,
            files: List[str] = None,
            texts: List[str] = None
    ) -> bool:
        """更新角色知识库（增量添加）"""
        vectorstore = await self.get_character_vectorstore(character_id)

        if not vectorstore:
            # 如果不存在，创建新的
            return await self.create_character_knowledge_base(character_id, files, texts)

        try:
            documents = []

            # 处理新文件
            if files:
                for file_path in files:
                    docs = await self._load_documents_from_file(file_path)
                    documents.extend(docs)

            # 处理新文本
            if texts:
                for i, text in enumerate(texts):
                    doc = Document(
                        page_content=text,
                        metadata={"source": f"text_update_{i}", "character_id": character_id}
                    )
                    documents.append(doc)

            if documents:
                # 分割文档
                split_docs = self.text_splitter.split_documents(documents)

                # 添加到现有向量数据库
                vectorstore.add_documents(split_docs)
                vectorstore.persist()

            return True

        except Exception as e:
            print(f"更新知识库失败: {e}")
            return False


# 全局RAG服务实例
rag_service = RAGService()