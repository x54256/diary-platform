-- 统一搜索语义增强（增量）：事件语义分块向量表 + pgvector 扩展 + HNSW 索引。
--
-- 本迁移与 036/037（关键词 pg_trgm search_text 触发器）并行不冲突：
-- 关键词分支逻辑保持不变，本表仅服务于新增的语义（embedding）分支。
-- 历史事件不在本迁移中回填（代码阶段仅对新事件/新分析做增量同步）。
--
-- 执行前提：目标 PostgreSQL 已安装 pgvector 服务端扩展（随 PG 一同安装；
-- 与现有 pg_trgm 扩展并存）。HNSW 索引需 pgvector >= 0.5（空表可直接构建）。

-- 1. 启用 pgvector 扩展（提供 vector 类型与 <=> 余弦距离算子）
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. 语义分块表：每个事件最多 3 块（fact / self_understanding / cognition）。
--    embedding 维度固定 N=1024（qwen3.7-text-embedding 默认维）。
CREATE TABLE IF NOT EXISTS event_embedding_chunks (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id    UUID NOT NULL REFERENCES diary_events(id) ON DELETE CASCADE,
    chunk_type  TEXT NOT NULL,                              -- fact / self_understanding / cognition
    content     TEXT NOT NULL,                             -- 分块纯文本（调试 / 回溯用，不外发）
    embedding   vector(1024) NOT NULL,                     -- 语义向量（与模型绑定，换模型需重算）
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 3. 唯一约束：(event_id, chunk_type) 保证每事件每层至多一条；upsert 时使用。
CREATE UNIQUE INDEX IF NOT EXISTS uq_event_embedding_chunks_event_chunk
    ON event_embedding_chunks (event_id, chunk_type);

-- 4. 事件级普通索引（按事件反查分块 / 清理孤儿分块）。
CREATE INDEX IF NOT EXISTS ix_event_embedding_chunks_event_id
    ON event_embedding_chunks (event_id);

-- 5. HNSW 余弦索引：加速 <=> 余弦距离最近邻召回（需 pgvector >= 0.5）。
CREATE INDEX IF NOT EXISTS ix_event_embedding_chunks_embedding
    ON event_embedding_chunks USING hnsw (embedding vector_cosine_ops);
