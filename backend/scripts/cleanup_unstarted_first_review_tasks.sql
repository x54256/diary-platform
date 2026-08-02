-- 清理历史遗留的“未由用户启动的首次回顾任务”。
--
-- 适用范围：trigger_type 为 AUTO 或 MANUAL、完整生成、没有用户启动审计，且仍处于
-- PENDING_START / QUEUED / RUNNING 的任务。不会删除已生成的回顾版本、回顾壳或 LLM 调用审计；
-- llm_call_logs.review_task_id 会因外键 ON DELETE SET NULL 自动解除关联。
--
-- 执行前必须停止应用，避免 worker 在清理过程中领取 QUEUED 任务。

BEGIN;

CREATE TEMP TABLE cleanup_review_tasks ON COMMIT DROP AS
SELECT id, source_set_id
FROM review_tasks
WHERE trigger_type IN ('AUTO', 'MANUAL')
  AND generation_mode = 'FULL'
  AND requested_start_at IS NULL
  AND started_by_user_id IS NULL
  AND status IN ('PENDING_START', 'QUEUED', 'RUNNING');

CREATE TEMP TABLE cleanup_source_sets ON COMMIT DROP AS
SELECT DISTINCT source_set_id AS id
FROM cleanup_review_tasks
WHERE source_set_id IS NOT NULL;

CREATE TEMP TABLE cleanup_sources ON COMMIT DROP AS
SELECT DISTINCT item.source_id AS id
FROM review_source_set_items item
JOIN cleanup_source_sets source_set ON source_set.id = item.source_set_id;

-- 执行前核对：daily_digests 会随 review_tasks 级联删除。
SELECT
    (SELECT count(*) FROM cleanup_review_tasks) AS review_task_count,
    (SELECT count(*) FROM review_daily_digests digest
      JOIN cleanup_review_tasks task ON task.id = digest.review_task_id) AS daily_digest_count,
    (SELECT count(*) FROM cleanup_source_sets) AS candidate_source_set_count,
    (SELECT count(*) FROM cleanup_sources) AS candidate_source_count;

DELETE FROM review_tasks
WHERE id IN (SELECT id FROM cleanup_review_tasks);

-- 只删除没有被版本或其他任务继续使用的来源集。
DELETE FROM review_source_sets source_set
WHERE source_set.id IN (SELECT id FROM cleanup_source_sets)
  AND NOT EXISTS (
      SELECT 1 FROM review_versions version
      WHERE version.source_set_id = source_set.id
  )
  AND NOT EXISTS (
      SELECT 1 FROM review_tasks task
      WHERE task.source_set_id = source_set.id
  );

-- 只删除上述来源集中、现已不属于任何来源集的孤立来源。
DELETE FROM review_sources source
WHERE source.id IN (SELECT id FROM cleanup_sources)
  AND NOT EXISTS (
      SELECT 1 FROM review_source_set_items item
      WHERE item.source_id = source.id
  );

COMMIT;
