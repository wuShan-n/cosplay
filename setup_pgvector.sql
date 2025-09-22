-- 安装 pgvector 扩展
CREATE EXTENSION IF NOT EXISTS vector;

-- 创建索引以加速向量搜索
-- 在 knowledge_chunks 表创建后运行这个
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_embedding
ON knowledge_chunks
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

-- 可选：为更好的性能，可以调整这些参数
ALTER SYSTEM SET maintenance_work_mem = '256MB';
ALTER SYSTEM SET max_parallel_workers_per_gather = 4;
ALTER SYSTEM SET max_parallel_workers = 8;
ALTER SYSTEM SET max_parallel_maintenance_workers = 4;

-- 重新加载配置
SELECT pg_reload_conf();