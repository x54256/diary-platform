-- 破坏性重构：日记级混合搜索。
-- 旧 diary_events.search_text 触发器和旧 event_embedding_chunks 数据不再使用；
-- 历史数据不会在本迁移或应用启动时回填。新建/更新事件才建立索引。

DROP TRIGGER IF EXISTS event_search_vector_event_tg ON diary_events;
DROP TRIGGER IF EXISTS event_search_vector_analysis_tg ON analysis_items;
DROP FUNCTION IF EXISTS compute_event_search_vector(UUID);
DROP FUNCTION IF EXISTS trg_event_search_vector_on_event();
DROP FUNCTION IF EXISTS trg_event_search_vector_on_analysis();
DROP INDEX IF EXISTS ix_diary_events_search_text;
ALTER TABLE diary_events DROP COLUMN IF EXISTS search_text;

CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE search_keyword_segments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    diary_id UUID NOT NULL REFERENCES diaries(id) ON DELETE CASCADE,
    event_id UUID NOT NULL REFERENCES diary_events(id) ON DELETE CASCADE,
    analysis_run_id UUID NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_search_keyword_segments_content
    ON search_keyword_segments USING GIN (content gin_trgm_ops);
CREATE INDEX ix_search_keyword_segments_diary ON search_keyword_segments(diary_id);
CREATE INDEX ix_search_keyword_segments_event ON search_keyword_segments(event_id);

-- 不兼容旧块：重建以加入 analysis_run_id，并将层名 fact 改为 event_content。
DROP TABLE IF EXISTS event_embedding_chunks CASCADE;
CREATE TABLE event_embedding_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID NOT NULL REFERENCES diary_events(id) ON DELETE CASCADE,
    analysis_run_id UUID NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
    chunk_type TEXT NOT NULL CHECK (chunk_type IN ('event_content', 'self_understanding', 'cognition')),
    content TEXT NOT NULL,
    embedding vector(1024) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_event_embedding_chunks_event_chunk UNIQUE(event_id, chunk_type)
);
CREATE INDEX ix_event_embedding_chunks_event_id ON event_embedding_chunks(event_id);
CREATE INDEX ix_event_embedding_chunks_embedding
    ON event_embedding_chunks USING hnsw (embedding vector_cosine_ops);

CREATE TABLE search_semantic_index_states (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID NOT NULL REFERENCES diary_events(id) ON DELETE CASCADE,
    analysis_run_id UUID NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
    chunk_type TEXT NOT NULL CHECK (chunk_type IN ('event_content', 'self_understanding', 'cognition')),
    content_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('PENDING', 'READY')),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_search_semantic_state_event_chunk UNIQUE(event_id, chunk_type)
);
CREATE INDEX ix_search_semantic_states_status ON search_semantic_index_states(status);
