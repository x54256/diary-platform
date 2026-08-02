-- 定期回顾：可靠修订号、版本、来源、持久化任务与用户操作。

-- 先以可空列回填旧数据，再收紧约束。旧的脏日记使原文与整理修订号错开，
-- 避免将明知过期的整理/分析结果误判为当前来源。
ALTER TABLE diaries ADD COLUMN IF NOT EXISTS content_revision INTEGER;
ALTER TABLE diary_organized ADD COLUMN IF NOT EXISTS source_content_revision INTEGER;
ALTER TABLE diary_organized ADD COLUMN IF NOT EXISTS structured_revision INTEGER;
ALTER TABLE analysis_runs ADD COLUMN IF NOT EXISTS source_structured_revision INTEGER;

UPDATE diaries
SET content_revision = CASE WHEN is_dirty THEN 2 ELSE 1 END
WHERE content_revision IS NULL;

UPDATE diary_organized SET source_content_revision = 1 WHERE source_content_revision IS NULL;
UPDATE diary_organized SET structured_revision = 1 WHERE structured_revision IS NULL;
UPDATE analysis_runs SET source_structured_revision = 1 WHERE source_structured_revision IS NULL;

ALTER TABLE diaries ALTER COLUMN content_revision SET DEFAULT 1;
ALTER TABLE diaries ALTER COLUMN content_revision SET NOT NULL;
ALTER TABLE diary_organized ALTER COLUMN source_content_revision SET DEFAULT 1;
ALTER TABLE diary_organized ALTER COLUMN source_content_revision SET NOT NULL;
ALTER TABLE diary_organized ALTER COLUMN structured_revision SET DEFAULT 1;
ALTER TABLE diary_organized ALTER COLUMN structured_revision SET NOT NULL;
ALTER TABLE analysis_runs ALTER COLUMN source_structured_revision SET DEFAULT 1;
ALTER TABLE analysis_runs ALTER COLUMN source_structured_revision SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_diaries_content_revision') THEN
        ALTER TABLE diaries ADD CONSTRAINT ck_diaries_content_revision CHECK (content_revision > 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_diary_organized_revisions') THEN
        ALTER TABLE diary_organized ADD CONSTRAINT ck_diary_organized_revisions
            CHECK (source_content_revision > 0 AND structured_revision > 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_analysis_runs_source_revision') THEN
        ALTER TABLE analysis_runs ADD CONSTRAINT ck_analysis_runs_source_revision
            CHECK (source_structured_revision > 0);
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS review_source_sets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    status VARCHAR(16) NOT NULL DEFAULT 'BUILDING',
    input_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_review_source_sets_status CHECK (status IN ('BUILDING', 'READY', 'ABANDONED'))
);

CREATE INDEX IF NOT EXISTS ix_review_source_sets_user_created
    ON review_source_sets(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS reviews (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    review_type VARCHAR(16) NOT NULL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    current_version_id UUID,
    is_unread BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_reviews_user_type_period UNIQUE (user_id, review_type, period_start, period_end),
    CONSTRAINT ck_reviews_period_order CHECK (period_end >= period_start),
    CONSTRAINT ck_reviews_type CHECK (review_type IN ('WEEK', 'MONTH', 'QUARTER', 'YEAR'))
);

CREATE INDEX IF NOT EXISTS ix_reviews_user_period_end
    ON reviews(user_id, period_end DESC);

CREATE TABLE IF NOT EXISTS review_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    review_id UUID NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id),
    version_no INTEGER NOT NULL,
    version_type VARCHAR(24) NOT NULL,
    base_version_id UUID REFERENCES review_versions(id) ON DELETE SET NULL,
    source_set_id UUID NOT NULL REFERENCES review_source_sets(id),
    event_document JSONB NOT NULL DEFAULT '{}'::jsonb,
    analysis_document JSONB NOT NULL DEFAULT '{}'::jsonb,
    summary VARCHAR(120) NOT NULL DEFAULT '',
    analysis_stale BOOLEAN NOT NULL DEFAULT FALSE,
    superseded_at_creation BOOLEAN NOT NULL DEFAULT FALSE,
    missing_periods JSONB NOT NULL DEFAULT '[]'::jsonb,
    event_model_info JSONB,
    analysis_model_info JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_review_versions_number UNIQUE (review_id, version_no),
    CONSTRAINT ck_review_versions_positive_number CHECK (version_no > 0),
    CONSTRAINT ck_review_versions_type CHECK (
        version_type IN ('GENERATED', 'REGENERATED', 'EVENT_EDITED', 'ANALYSIS_UPDATED')
    )
);

CREATE INDEX IF NOT EXISTS ix_review_versions_review_created
    ON review_versions(review_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_review_versions_user ON review_versions(user_id);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_reviews_current_version') THEN
        ALTER TABLE reviews
            ADD CONSTRAINT fk_reviews_current_version
            FOREIGN KEY (current_version_id) REFERENCES review_versions(id) ON DELETE SET NULL;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS review_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    review_id UUID NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id),
    trigger_type VARCHAR(16) NOT NULL,
    generation_mode VARCHAR(20) NOT NULL DEFAULT 'FULL',
    base_version_id UUID REFERENCES review_versions(id) ON DELETE SET NULL,
    retry_of_task_id UUID REFERENCES review_tasks(id) ON DELETE SET NULL,
    source_set_id UUID REFERENCES review_source_sets(id),
    status VARCHAR(24) NOT NULL DEFAULT 'QUEUED',
    current_step VARCHAR(24) NOT NULL DEFAULT 'FREEZE_SOURCES',
    freeze_attempts INTEGER NOT NULL DEFAULT 0,
    event_attempts INTEGER NOT NULL DEFAULT 0,
    analysis_attempts INTEGER NOT NULL DEFAULT 0,
    available_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    lease_until TIMESTAMP,
    run_token UUID,
    source_snapshot_ready BOOLEAN NOT NULL DEFAULT FALSE,
    event_result JSONB,
    analysis_result JSONB,
    error_code VARCHAR(64),
    error_message TEXT,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    result_version_id UUID REFERENCES review_versions(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_review_tasks_trigger CHECK (trigger_type IN ('AUTO', 'MANUAL', 'REGENERATE', 'RETRY')),
    CONSTRAINT ck_review_tasks_mode CHECK (generation_mode IN ('FULL', 'ANALYSIS_ONLY')),
    CONSTRAINT ck_review_tasks_status CHECK (
        status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'SKIPPED_NO_DATA')
    ),
    CONSTRAINT ck_review_tasks_step CHECK (
        current_step IN ('FREEZE_SOURCES', 'LOAD_BASE_EVENT', 'EVENT_ORGANIZE', 'ANALYSIS_ACTION', 'PERSIST_VERSION')
    ),
    CONSTRAINT ck_review_tasks_attempts CHECK (
        freeze_attempts >= 0 AND event_attempts >= 0 AND analysis_attempts >= 0
    ),
    CONSTRAINT ck_review_tasks_analysis_only_no_event_attempts CHECK (
        generation_mode <> 'ANALYSIS_ONLY' OR event_attempts = 0
    ),
    CONSTRAINT ck_review_tasks_ready_has_source_set CHECK (
        NOT source_snapshot_ready OR source_set_id IS NOT NULL
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_review_tasks_active_review
    ON review_tasks(review_id)
    WHERE status IN ('QUEUED', 'RUNNING');
CREATE INDEX IF NOT EXISTS ix_review_tasks_user_created
    ON review_tasks(user_id, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS ix_review_tasks_claim
    ON review_tasks(status, available_at, lease_until);

ALTER TABLE llm_call_logs
    ADD COLUMN IF NOT EXISTS review_task_id UUID REFERENCES review_tasks(id) ON DELETE SET NULL;
ALTER TABLE llm_call_logs
    ADD COLUMN IF NOT EXISTS completion_tokens INTEGER;
CREATE INDEX IF NOT EXISTS ix_llm_call_logs_review_task
    ON llm_call_logs(review_task_id);

CREATE TABLE IF NOT EXISTS review_sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    root_fact_id VARCHAR(200) NOT NULL,
    source_type VARCHAR(32) NOT NULL,
    root_source_type VARCHAR(32) NOT NULL,
    fact_kind VARCHAR(24) NOT NULL,
    source_date DATE NOT NULL,
    period_role VARCHAR(20) NOT NULL,
    relative_position VARCHAR(8),
    origin_review_id UUID REFERENCES reviews(id) ON DELETE SET NULL,
    origin_review_version_id UUID REFERENCES review_versions(id) ON DELETE SET NULL,
    origin_content_item_type VARCHAR(32),
    origin_content_item_id UUID,
    origin_content_item_key VARCHAR(200),
    lineage JSONB NOT NULL DEFAULT '[]'::jsonb,
    content TEXT NOT NULL,
    snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_review_sources_type CHECK (
        source_type IN (
            'DIARY_EVENT', 'SCHEDULE_OCCURRENCE', 'LOWER_REVIEW_EVENT',
            'LOWER_REVIEW_ANALYSIS', 'PRIOR_REVIEW_EVENT', 'USER_FACT_CORRECTION'
        )
    ),
    CONSTRAINT ck_review_sources_fact_kind CHECK (
        fact_kind IN (
            'USER_FACT', 'USER_SELF_REPORT', 'SCHEDULE_RECORD',
            'AI_ANALYSIS', 'USER_CORRECTION', 'REVIEW_DERIVED'
        )
    ),
    CONSTRAINT ck_review_sources_period_role CHECK (
        period_role IN ('CURRENT', 'CONTEXT_ONLY', 'OUT_OF_PERIOD')
    ),
    CONSTRAINT ck_review_sources_relative_position CHECK (
        relative_position IS NULL OR relative_position IN ('BEFORE', 'AFTER')
    ),
    CONSTRAINT ck_review_sources_period_position CHECK (
        (period_role = 'CURRENT' AND relative_position IS NULL)
        OR (period_role <> 'CURRENT' AND relative_position IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS ix_review_sources_user_root_fact
    ON review_sources(user_id, root_fact_id);
CREATE INDEX IF NOT EXISTS ix_review_sources_origin_version
    ON review_sources(origin_review_version_id);

CREATE TABLE IF NOT EXISTS review_source_set_items (
    source_set_id UUID NOT NULL REFERENCES review_source_sets(id) ON DELETE CASCADE,
    source_id UUID NOT NULL REFERENCES review_sources(id) ON DELETE RESTRICT,
    PRIMARY KEY (source_set_id, source_id)
);

CREATE INDEX IF NOT EXISTS ix_review_source_set_items_source
    ON review_source_set_items(source_id);

CREATE TABLE IF NOT EXISTS review_version_dependencies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id UUID NOT NULL REFERENCES review_versions(id) ON DELETE CASCADE,
    dependency_type VARCHAR(24) NOT NULL,
    dependency_review_id UUID REFERENCES reviews(id) ON DELETE SET NULL,
    dependency_version_id UUID REFERENCES review_versions(id) ON DELETE SET NULL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    status VARCHAR(24) NOT NULL,
    context_only BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT uq_review_dependencies_period UNIQUE (
        version_id, dependency_type, period_start, period_end
    ),
    CONSTRAINT ck_review_dependencies_type CHECK (
        dependency_type IN ('LOWER_PERIOD', 'PRIOR_SAME_LEVEL')
    ),
    CONSTRAINT ck_review_dependencies_status CHECK (
        status IN ('AVAILABLE', 'MISSING', 'FAILED', 'SKIPPED_NO_DATA')
    ),
    CONSTRAINT ck_review_dependencies_period_order CHECK (period_end >= period_start),
    CONSTRAINT ck_review_dependencies_available_version CHECK (
        status <> 'AVAILABLE' OR dependency_version_id IS NOT NULL
    )
);

CREATE INDEX IF NOT EXISTS ix_review_dependencies_dependency_review
    ON review_version_dependencies(dependency_review_id);

CREATE TABLE IF NOT EXISTS review_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id UUID NOT NULL REFERENCES review_versions(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id),
    analysis_item_id UUID NOT NULL,
    angle_code VARCHAR(40) NOT NULL,
    rating INTEGER,
    comment TEXT,
    is_inherited BOOLEAN NOT NULL DEFAULT FALSE,
    source_feedback_id UUID REFERENCES review_feedback(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_review_feedback_analysis_item UNIQUE (version_id, analysis_item_id),
    CONSTRAINT ck_review_feedback_rating CHECK (rating IS NULL OR rating BETWEEN 1 AND 5),
    CONSTRAINT ck_review_feedback_has_content CHECK (
        rating IS NOT NULL OR NULLIF(BTRIM(comment), '') IS NOT NULL
    ),
    CONSTRAINT ck_review_feedback_angle CHECK (
        angle_code IN (
            'EMOTION_REGULATION', 'BEHAVIOR_EXECUTION', 'DECISION_PROBLEM_SOLVING',
            'ATTENTION_MOTIVATION_VALUES', 'COGNITION_LEARNING', 'CAPABILITY_GROWTH',
            'RELATIONSHIP_SOCIAL_PSYCHOLOGY'
        )
    )
);

CREATE INDEX IF NOT EXISTS ix_review_feedback_user ON review_feedback(user_id);

CREATE TABLE IF NOT EXISTS review_actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id UUID NOT NULL REFERENCES review_versions(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id),
    primary_domain VARCHAR(32) NOT NULL,
    related_domains JSONB NOT NULL DEFAULT '[]'::jsonb,
    content TEXT NOT NULL,
    edited_content TEXT,
    rationale TEXT,
    status VARCHAR(16) NOT NULL DEFAULT 'CANDIDATE',
    source_action_id UUID REFERENCES review_actions(id) ON DELETE SET NULL,
    is_inherited BOOLEAN NOT NULL DEFAULT FALSE,
    basis_analysis_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    basis_source_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    verification_rule JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_review_actions_status CHECK (status IN ('CANDIDATE', 'CONFIRMED', 'IGNORED')),
    CONSTRAINT ck_review_actions_domain CHECK (
        primary_domain IN (
            'WORK_CAREER', 'HEALTH_WELLBEING', 'RELATIONSHIPS_SOCIAL',
            'LEARNING_GROWTH', 'LIFE_RESOURCES', 'LEISURE_EXPERIENCE'
        )
    )
);

CREATE INDEX IF NOT EXISTS ix_review_actions_version_domain
    ON review_actions(version_id, primary_domain);
CREATE INDEX IF NOT EXISTS ix_review_actions_source
    ON review_actions(source_action_id);

CREATE TABLE IF NOT EXISTS review_action_checks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id UUID NOT NULL REFERENCES review_versions(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id),
    previous_action_id UUID NOT NULL REFERENCES review_actions(id) ON DELETE RESTRICT,
    check_status VARCHAR(32) NOT NULL,
    explanation TEXT NOT NULL,
    evidence_source_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_review_action_checks_previous_action UNIQUE (version_id, previous_action_id),
    CONSTRAINT ck_review_action_checks_status CHECK (
        check_status IN (
            'FULFILLED', 'PARTIALLY_FULFILLED',
            'EXPLICITLY_NOT_FULFILLED', 'NOT_ASSESSABLE'
        )
    )
);

CREATE INDEX IF NOT EXISTS ix_review_action_checks_user ON review_action_checks(user_id);

-- 回顾对话按固定版本唯一复用，防止并发请求创建重复对话。
CREATE UNIQUE INDEX IF NOT EXISTS uq_dialogs_user_review_source
    ON dialogs(user_id, source_type, source_id)
    WHERE source_type = 'review' AND source_id IS NOT NULL;
