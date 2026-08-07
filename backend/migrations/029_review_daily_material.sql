-- 每日周回顾素材：以单一完整文档替换旧的两段每日提炼。
begin;
DELETE FROM review_daily_digests;

-- 未完成的完整生成任务必须使用新快照和新每日素材重新开始。
CREATE TEMP TABLE review_daily_material_reset_sources ON COMMIT DROP AS
SELECT DISTINCT task.source_set_id
FROM review_tasks AS task
WHERE task.generation_mode = 'FULL'
  AND task.status IN ('PENDING_START', 'QUEUED', 'RUNNING')
  AND task.source_set_id IS NOT NULL;

CREATE TEMP TABLE review_daily_material_reset_source_ids ON COMMIT DROP AS
SELECT DISTINCT item.source_id
FROM review_source_set_items AS item
         JOIN review_daily_material_reset_sources AS reset_source
              ON reset_source.source_set_id = item.source_set_id;

UPDATE review_tasks
SET source_set_id = NULL,
    source_snapshot_ready = FALSE,
    event_result = NULL,
    analysis_result = NULL,
    current_step = 'FREEZE_SOURCES',
    status = 'QUEUED',
    run_token = NULL,
    lease_until = NULL,
    available_at = CURRENT_TIMESTAMP
WHERE generation_mode = 'FULL'
  AND status IN ('PENDING_START', 'QUEUED', 'RUNNING');

DELETE FROM review_source_sets AS source_set
    USING review_daily_material_reset_sources AS reset_source
WHERE source_set.id = reset_source.source_set_id;

DELETE FROM review_sources AS source
    USING review_daily_material_reset_source_ids AS reset_source
WHERE source.id = reset_source.source_id
  AND NOT EXISTS (
    SELECT 1 FROM review_source_set_items AS item WHERE item.source_id = source.id
);

ALTER TABLE review_daily_digests
    RENAME COLUMN event_document TO material_document;
ALTER TABLE review_daily_digests
    RENAME COLUMN event_model_info TO model_info;

ALTER TABLE review_daily_digests
    DROP COLUMN analysis_document,
    DROP COLUMN analysis_model_info;

ALTER TABLE review_daily_digests
    DROP CONSTRAINT IF EXISTS ck_review_daily_digests_status;
ALTER TABLE review_daily_digests
    ADD CONSTRAINT ck_review_daily_digests_status
        CHECK (status IN ('EMPTY', 'READY', 'FAILED'));

UPDATE model_step_settings
SET step_key = 'review_daily_material', updated_at = CURRENT_TIMESTAMP
WHERE step_key = 'review_daily_event_digest';

DELETE FROM model_step_settings
WHERE step_key = 'review_daily_analysis_digest';
commit;