CREATE TABLE IF NOT EXISTS knowledge_tasks (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id),
    diary_id UUID NOT NULL REFERENCES diaries(id) ON DELETE RESTRICT,
    source_diary_organized_id UUID NOT NULL REFERENCES diary_organized(id) ON DELETE RESTRICT,
    source_structured_revision INTEGER NOT NULL,
    source_analysis_run_id UUID NOT NULL REFERENCES analysis_runs(id) ON DELETE RESTRICT,
    status VARCHAR(16) NOT NULL DEFAULT 'QUEUED' CHECK (status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED')),
    current_step VARCHAR(32) CHECK (current_step IS NULL OR current_step IN ('VALIDATE_SOURCE','PREPARE_BATCHES','EXTRACT_BATCH','PUBLISH')),
    retry_count INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
    available_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    lease_until TIMESTAMP,
    run_token UUID,
    error_code VARCHAR(64),
    error_message TEXT,
    checkpoint_cleaned_at TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_knowledge_tasks_user_active
    ON knowledge_tasks(user_id) WHERE status IN ('QUEUED','RUNNING');
CREATE UNIQUE INDEX IF NOT EXISTS uq_knowledge_tasks_source_active
    ON knowledge_tasks(diary_id, source_structured_revision, source_analysis_run_id)
    WHERE status IN ('QUEUED','RUNNING');
CREATE INDEX IF NOT EXISTS ix_knowledge_tasks_queue
    ON knowledge_tasks(status, available_at, created_at);

CREATE TABLE IF NOT EXISTS knowledge_deposits (
    diary_id UUID PRIMARY KEY REFERENCES diaries(id) ON DELETE RESTRICT,
    user_id UUID NOT NULL REFERENCES users(id),
    task_id UUID NOT NULL UNIQUE REFERENCES knowledge_tasks(id) ON DELETE RESTRICT,
    source_diary_organized_id UUID NOT NULL REFERENCES diary_organized(id) ON DELETE RESTRICT,
    source_structured_revision INTEGER NOT NULL,
    source_analysis_run_id UUID NOT NULL REFERENCES analysis_runs(id) ON DELETE RESTRICT,
    completed_stage VARCHAR(32) NOT NULL DEFAULT 'ATOMIC_EVENTS' CHECK (completed_stage = 'ATOMIC_EVENTS'),
    deposited_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_knowledge_deposits_user
    ON knowledge_deposits(user_id, deposited_at);

CREATE TABLE IF NOT EXISTS knowledge_atomic_events (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id),
    diary_id UUID NOT NULL REFERENCES knowledge_deposits(diary_id) ON DELETE RESTRICT,
    source_diary_event_id UUID NOT NULL REFERENCES diary_events(id) ON DELETE RESTRICT,
    source_order INTEGER NOT NULL CHECK (source_order >= 0),
    title VARCHAR(20) NOT NULL CHECK (char_length(title) BETWEEN 1 AND 20),
    source_fragments JSONB NOT NULL CHECK (jsonb_typeof(source_fragments) = 'array'),
    summary TEXT NOT NULL,
    occurred_on DATE NOT NULL,
    occurred_time TIME,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_knowledge_atomic_events_source_order
        UNIQUE (user_id, diary_id, source_diary_event_id, source_order)
);
CREATE INDEX IF NOT EXISTS ix_knowledge_atomic_events_user_time
    ON knowledge_atomic_events(user_id, occurred_on DESC, occurred_time DESC NULLS LAST, created_at DESC, id DESC);
