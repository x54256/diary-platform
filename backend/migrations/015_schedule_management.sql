CREATE TABLE IF NOT EXISTS schedule_tasks (
    id UUID PRIMARY KEY, user_id UUID NOT NULL REFERENCES users(id), source_task_id UUID REFERENCES schedule_tasks(id),
    title VARCHAR(200) NOT NULL, is_all_day BOOLEAN NOT NULL DEFAULT FALSE, start_date DATE NOT NULL,
    start_time TIME, end_time TIME, recurrence_type VARCHAR(32) NOT NULL DEFAULT 'NONE', interval VARCHAR(10) NOT NULL DEFAULT '1',
    weekdays VARCHAR(32), month_day VARCHAR(2), nth_week VARCHAR(1), nth_weekday VARCHAR(1), recurrence_until DATE, recurrence_count VARCHAR(10),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(), updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CHECK (is_all_day OR (start_time IS NOT NULL AND end_time IS NOT NULL AND end_time > start_time))
);
CREATE TABLE IF NOT EXISTS schedule_occurrences (
    id UUID PRIMARY KEY, user_id UUID NOT NULL REFERENCES users(id), task_id UUID NOT NULL REFERENCES schedule_tasks(id) ON DELETE CASCADE,
    scheduled_date DATE NOT NULL, title VARCHAR(200) NOT NULL, is_all_day BOOLEAN NOT NULL DEFAULT FALSE, start_time TIME, end_time TIME,
    status VARCHAR(20) NOT NULL DEFAULT 'pending', completed_at TIMESTAMP, overdue_reason TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(), updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_schedule_occurrence_date UNIQUE(task_id, scheduled_date)
);
CREATE INDEX IF NOT EXISTS ix_schedule_occurrences_user_date_status ON schedule_occurrences(user_id, scheduled_date, status);
