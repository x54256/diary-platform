-- 管理端按日期范围重建关键词与语义索引的持久化任务。
CREATE TABLE search_index_rebuild_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    operator_user_id UUID NOT NULL REFERENCES users(id),
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'cancelled')) DEFAULT 'queued',
    total_events INTEGER NOT NULL DEFAULT 0,
    processed_events INTEGER NOT NULL DEFAULT 0,
    succeeded_events INTEGER NOT NULL DEFAULT 0,
    failed_events INTEGER NOT NULL DEFAULT 0,
    last_event_id UUID NULL,
    failure_details TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ NULL,
    finished_at TIMESTAMPTZ NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (start_date <= end_date)
);
CREATE INDEX ix_search_index_rebuild_jobs_status_created
    ON search_index_rebuild_jobs(status, created_at);
