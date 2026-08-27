-- 知识库事项阶段：knowledge_matters 表 + knowledge_atomic_events 增加归属与向量 + 阶段/步骤枚举放宽。
--
-- 设计依据：docs/系统设计/知识库/知识库事项管理设计.md（2026-08-24 基线）。
-- 执行前提：迁移 038 已启用 pgvector 扩展；存量知识事件的 matter_id 与 embedding 保持 NULL
-- （不参与召回、不进入任何事项，对应"只管增量"决策）。

-- 1. 事项表：跨时间持续发展的具体事情线索。
CREATE TABLE IF NOT EXISTS knowledge_matters (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID NOT NULL REFERENCES users(id),
    name          VARCHAR(30) NOT NULL CHECK (char_length(name) BETWEEN 1 AND 30),
    overview      TEXT NOT NULL,
    status        VARCHAR(16) NOT NULL CHECK (status IN ('ONGOING','ENDED','PAUSED')),
    started_on    DATE NOT NULL,
    last_event_on DATE NOT NULL,
    event_count   INTEGER NOT NULL CHECK (event_count >= 1),
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (started_on <= last_event_on)
);

CREATE INDEX IF NOT EXISTS ix_knowledge_matters_user_time
    ON knowledge_matters(user_id, last_event_on DESC, updated_at DESC, id DESC);

-- 2. 知识事件归属（可空）与语义向量（可空，1024 维与 EMBEDDING 配置一致）。
ALTER TABLE knowledge_atomic_events
    ADD COLUMN IF NOT EXISTS matter_id UUID REFERENCES knowledge_matters(id) ON DELETE RESTRICT;
ALTER TABLE knowledge_atomic_events
    ADD COLUMN IF NOT EXISTS embedding vector(1024);

CREATE INDEX IF NOT EXISTS ix_knowledge_atomic_events_matter_time
    ON knowledge_atomic_events(matter_id, occurred_on DESC, occurred_time DESC NULLS LAST, id DESC);

-- 3. HNSW 余弦索引：事项匹配的纯事件路召回（WHERE embedding IS NOT NULL）。
CREATE INDEX IF NOT EXISTS ix_knowledge_atomic_events_embedding
    ON knowledge_atomic_events USING hnsw (embedding vector_cosine_ops);

-- 4. 沉淀阶段枚举放宽：事项匹配成功后 completed_stage 推进为 MATTERS。
ALTER TABLE knowledge_deposits DROP CONSTRAINT IF EXISTS ck_knowledge_deposits_stage;
ALTER TABLE knowledge_deposits
    ADD CONSTRAINT ck_knowledge_deposits_stage CHECK (completed_stage IN ('ATOMIC_EVENTS','MATTERS'));

-- 5. 任务步骤枚举放宽：流水线尾部追加 MATCH_MATTERS 节点。
ALTER TABLE knowledge_tasks DROP CONSTRAINT IF EXISTS ck_knowledge_tasks_step;
ALTER TABLE knowledge_tasks
    ADD CONSTRAINT ck_knowledge_tasks_step CHECK (current_step IS NULL OR current_step IN (
        'VALIDATE_SOURCE','PREPARE_BATCHES','EXTRACT_BATCH',
        'PREPARE_REVIEW_BATCHES','REVIEW_BATCH','PUBLISH','MATCH_MATTERS'
    ));
