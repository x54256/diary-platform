CREATE TABLE IF NOT EXISTS schedule_maintenance_jobs (
    id UUID PRIMARY KEY,
    task_id UUID NOT NULL REFERENCES schedule_tasks(id) ON DELETE CASCADE,
    operation VARCHAR(20) NOT NULL,
    scheduled_from DATE NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'queued',
    attempts INTEGER NOT NULL DEFAULT 0,
    available_at TIMESTAMP NOT NULL DEFAULT NOW(),
    last_error TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_schedule_maintenance_jobs_queue
    ON schedule_maintenance_jobs(status, available_at, created_at);
