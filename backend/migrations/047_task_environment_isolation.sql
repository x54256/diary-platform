-- 共享数据库时隔离不同部署环境的后台任务。
-- 历史数据属于现有生产库，统一回填为 production；新记录由应用写入 APP_ENV。

ALTER TABLE knowledge_tasks ADD COLUMN IF NOT EXISTS environment VARCHAR(32);
UPDATE knowledge_tasks SET environment = 'production' WHERE environment IS NULL;
ALTER TABLE knowledge_tasks ALTER COLUMN environment SET NOT NULL;
CREATE INDEX IF NOT EXISTS ix_knowledge_tasks_environment_queue
    ON knowledge_tasks (environment, status, available_at, created_at);
DROP INDEX IF EXISTS uq_knowledge_tasks_user_active;
CREATE UNIQUE INDEX uq_knowledge_tasks_user_active
    ON knowledge_tasks (environment, user_id)
    WHERE status IN ('QUEUED','RUNNING');
DROP INDEX IF EXISTS uq_knowledge_tasks_source_active;
CREATE UNIQUE INDEX uq_knowledge_tasks_source_active
    ON knowledge_tasks (environment, diary_id, source_structured_revision)
    WHERE status IN ('QUEUED','RUNNING');

ALTER TABLE review_tasks ADD COLUMN IF NOT EXISTS environment VARCHAR(32);
UPDATE review_tasks SET environment = 'production' WHERE environment IS NULL;
ALTER TABLE review_tasks ALTER COLUMN environment SET NOT NULL;
CREATE INDEX IF NOT EXISTS ix_review_tasks_environment_claim
    ON review_tasks (environment, status, available_at, lease_until);
DROP INDEX IF EXISTS uq_review_tasks_active_review;
CREATE UNIQUE INDEX uq_review_tasks_active_review
    ON review_tasks (environment, review_id)
    WHERE status IN ('PENDING_START','QUEUED','RUNNING');

ALTER TABLE transcription_batches ADD COLUMN IF NOT EXISTS environment VARCHAR(32);
UPDATE transcription_batches SET environment = 'production' WHERE environment IS NULL;
ALTER TABLE transcription_batches ALTER COLUMN environment SET NOT NULL;
CREATE INDEX IF NOT EXISTS ix_transcription_batches_environment_queue
    ON transcription_batches (environment, status, updated_at);
DROP INDEX IF EXISTS uq_transcription_active_user_date;
CREATE UNIQUE INDEX uq_transcription_active_user_date
    ON transcription_batches (environment, user_id, diary_date)
    WHERE status IN ('QUEUED', 'PROCESSING', 'PARTIAL_FAILED', 'FINALIZING');

ALTER TABLE schedule_maintenance_jobs ADD COLUMN IF NOT EXISTS environment VARCHAR(32);
UPDATE schedule_maintenance_jobs SET environment = 'production' WHERE environment IS NULL;
ALTER TABLE schedule_maintenance_jobs ALTER COLUMN environment SET NOT NULL;
CREATE INDEX IF NOT EXISTS ix_schedule_maintenance_environment_queue
    ON schedule_maintenance_jobs (environment, status, available_at, created_at);

ALTER TABLE search_index_rebuild_jobs ADD COLUMN IF NOT EXISTS environment VARCHAR(32);
UPDATE search_index_rebuild_jobs SET environment = 'production' WHERE environment IS NULL;
ALTER TABLE search_index_rebuild_jobs ALTER COLUMN environment SET NOT NULL;
CREATE INDEX IF NOT EXISTS ix_search_rebuild_environment_queue
    ON search_index_rebuild_jobs (environment, status, created_at);

ALTER TABLE backup_restore_records ADD COLUMN IF NOT EXISTS environment VARCHAR(32);
UPDATE backup_restore_records SET environment = 'production' WHERE environment IS NULL;
ALTER TABLE backup_restore_records ALTER COLUMN environment SET NOT NULL;
