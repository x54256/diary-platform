ALTER TABLE knowledge_tasks
    DROP CONSTRAINT IF EXISTS ck_knowledge_tasks_step;

ALTER TABLE knowledge_tasks
    DROP CONSTRAINT IF EXISTS knowledge_tasks_current_step_check;

ALTER TABLE knowledge_tasks
    ADD CONSTRAINT ck_knowledge_tasks_step
    CHECK (
        current_step IS NULL OR current_step IN (
            'VALIDATE_SOURCE',
            'PREPARE_BATCHES',
            'EXTRACT_BATCH',
            'PREPARE_REVIEW_BATCHES',
            'REVIEW_BATCH',
            'PUBLISH'
        )
    );

CREATE TABLE IF NOT EXISTS knowledge_event_reviews (
    id UUID PRIMARY KEY,
    knowledge_event_id UUID NOT NULL
        REFERENCES knowledge_atomic_events(id) ON DELETE CASCADE,
    task_id UUID NOT NULL
        REFERENCES knowledge_tasks(id) ON DELETE RESTRICT,
    issues JSONB NOT NULL DEFAULT '[]'::jsonb,
    content_changed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_knowledge_event_reviews_issues
        CHECK (jsonb_typeof(issues) = 'array'),
    CONSTRAINT uq_knowledge_event_reviews_event UNIQUE (knowledge_event_id)
);

-- CREATE TABLE IF NOT EXISTS 不会为已存在的表补加新约束。
ALTER TABLE knowledge_event_reviews
    DROP CONSTRAINT IF EXISTS ck_knowledge_event_reviews_issues;

ALTER TABLE knowledge_event_reviews
    ADD CONSTRAINT ck_knowledge_event_reviews_issues
    CHECK (jsonb_typeof(issues) = 'array');
