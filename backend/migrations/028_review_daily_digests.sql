-- 分层每日提炼、事件重要性与回顾任务手动启动。

ALTER TABLE diary_events ADD COLUMN IF NOT EXISTS ai_importance VARCHAR(8);
ALTER TABLE diary_events ADD COLUMN IF NOT EXISTS ai_importance_reason TEXT;
ALTER TABLE diary_events ADD COLUMN IF NOT EXISTS user_importance VARCHAR(8);
ALTER TABLE diary_events ADD COLUMN IF NOT EXISTS user_importance_reason TEXT;
ALTER TABLE diary_events ADD COLUMN IF NOT EXISTS importance_origin VARCHAR(24);
ALTER TABLE diary_events ADD COLUMN IF NOT EXISTS importance_updated_at TIMESTAMP;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_diary_events_ai_importance') THEN
        ALTER TABLE diary_events ADD CONSTRAINT ck_diary_events_ai_importance
            CHECK (ai_importance IS NULL OR ai_importance IN ('HIGH', 'MEDIUM', 'LOW'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_diary_events_user_importance') THEN
        ALTER TABLE diary_events ADD CONSTRAINT ck_diary_events_user_importance
            CHECK (user_importance IS NULL OR user_importance IN ('HIGH', 'MEDIUM', 'LOW'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_diary_events_importance_origin') THEN
        ALTER TABLE diary_events ADD CONSTRAINT ck_diary_events_importance_origin
            CHECK (importance_origin IS NULL OR importance_origin IN ('DIARY_ANALYSIS', 'LEGACY_BACKFILL'));
    END IF;
END $$;

ALTER TABLE review_tasks ADD COLUMN IF NOT EXISTS requested_start_at TIMESTAMP;
ALTER TABLE review_tasks ADD COLUMN IF NOT EXISTS started_by_user_id UUID REFERENCES users(id);

ALTER TABLE review_tasks DROP CONSTRAINT IF EXISTS ck_review_tasks_status;
ALTER TABLE review_tasks ADD CONSTRAINT ck_review_tasks_status CHECK (
    status IN ('PENDING_START', 'QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'SKIPPED_NO_DATA')
);

DROP INDEX IF EXISTS uq_review_tasks_active_review;
CREATE UNIQUE INDEX IF NOT EXISTS uq_review_tasks_active_review
    ON review_tasks(review_id)
    WHERE status IN ('PENDING_START', 'QUEUED', 'RUNNING');

CREATE TABLE IF NOT EXISTS review_daily_digests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    review_task_id UUID NOT NULL REFERENCES review_tasks(id) ON DELETE CASCADE,
    review_version_id UUID REFERENCES review_versions(id) ON DELETE SET NULL,
    source_set_id UUID NOT NULL REFERENCES review_source_sets(id),
    digest_date DATE NOT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'EMPTY',
    event_document JSONB NOT NULL DEFAULT '{}'::jsonb,
    analysis_document JSONB NOT NULL DEFAULT '{}'::jsonb,
    event_model_info JSONB,
    analysis_model_info JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_review_daily_digests_task_date UNIQUE (review_task_id, digest_date),
    CONSTRAINT ck_review_daily_digests_status CHECK (status IN ('EMPTY', 'EVENT_READY', 'ANALYSIS_READY', 'FAILED'))
);

CREATE INDEX IF NOT EXISTS ix_review_daily_digests_version
    ON review_daily_digests(review_version_id, digest_date);
