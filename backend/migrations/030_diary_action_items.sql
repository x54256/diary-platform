-- 日记独立行动项及其与现有日程任务的历史关联。

CREATE TABLE IF NOT EXISTS diary_action_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    diary_id UUID NOT NULL REFERENCES diaries(id) ON DELETE CASCADE,
    generation_run_id UUID NOT NULL REFERENCES analysis_runs(id),
    source_kind VARCHAR(20) NOT NULL,
    source_refs JSONB NOT NULL DEFAULT '{}'::jsonb,
    title VARCHAR(200) NOT NULL,
    is_all_day BOOLEAN NOT NULL DEFAULT TRUE,
    start_date DATE NOT NULL,
    start_time TIME,
    end_time TIME,
    recurrence_type VARCHAR(32) NOT NULL DEFAULT 'NONE',
    interval INTEGER NOT NULL DEFAULT 1,
    weekdays JSONB NOT NULL DEFAULT '[]'::jsonb,
    month_day INTEGER,
    nth_week INTEGER,
    nth_weekday INTEGER,
    recurrence_until DATE,
    recurrence_count INTEGER,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    completed_at TIMESTAMP,
    user_modified BOOLEAN NOT NULL DEFAULT FALSE,
    sort_order INTEGER NOT NULL DEFAULT 0,
    deleted_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_diary_action_items_diary_status
    ON diary_action_items(diary_id, status);
CREATE INDEX IF NOT EXISTS ix_diary_action_items_user_diary
    ON diary_action_items(user_id, diary_id);

CREATE TABLE IF NOT EXISTS diary_action_schedule_links (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    action_item_id UUID NOT NULL REFERENCES diary_action_items(id) ON DELETE CASCADE,
    schedule_task_id UUID REFERENCES schedule_tasks(id) ON DELETE SET NULL,
    schedule_task_snapshot_id UUID NOT NULL,
    completion_occurrence_id UUID REFERENCES schedule_occurrences(id) ON DELETE SET NULL,
    linked_at TIMESTAMP NOT NULL DEFAULT NOW(),
    unlinked_at TIMESTAMP,
    unlink_reason VARCHAR(32)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_diary_action_active_link
    ON diary_action_schedule_links(action_item_id)
    WHERE unlinked_at IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_schedule_active_action_link
    ON diary_action_schedule_links(schedule_task_id)
    WHERE unlinked_at IS NULL AND schedule_task_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_diary_action_links_schedule_task
    ON diary_action_schedule_links(schedule_task_id);
