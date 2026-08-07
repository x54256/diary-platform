-- 只读诊断单个回顾任务。
-- 用法：
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f backend/scripts/diagnose_review_task.sql
-- 默认诊断用户提供的任务；也可以通过 -v task_id='...' 覆盖。

\if :{?task_id}
\else
\set task_id '045a7413-b144-4e98-b30c-9ee6cec30ef2'
\endif

BEGIN READ ONLY;

SELECT
    'task' AS section,
    t.id,
    t.review_id,
    r.review_type,
    r.period_start,
    r.period_end,
    t.status,
    t.current_step,
    t.generation_mode,
    t.trigger_type,
    t.source_snapshot_ready,
    t.source_set_id,
    t.freeze_attempts,
    t.event_attempts,
    t.analysis_attempts,
    t.error_code,
    t.error_message,
    t.retry_of_task_id,
    t.started_at,
    t.completed_at,
    t.created_at,
    t.updated_at,
    CASE WHEN t.event_result IS NULL THEN FALSE ELSE TRUE END AS has_event_result,
    jsonb_object_keys(COALESCE(t.event_result, '{}'::jsonb)) AS event_result_key
FROM review_tasks t
JOIN reviews r ON r.id = t.review_id
WHERE t.id = :'task_id'::uuid;

SELECT
    'daily_digest_summary' AS section,
    d.status,
    COUNT(*) AS row_count,
    MIN(d.digest_date) AS first_date,
    MAX(d.digest_date) AS last_date,
    COUNT(*) FILTER (WHERE d.event_document IS NULL OR d.event_document = '{}'::jsonb) AS empty_event_document_count,
    COUNT(*) FILTER (WHERE d.status = 'FAILED') AS failed_count
FROM review_daily_digests d
WHERE d.review_task_id = :'task_id'::uuid
GROUP BY d.status
ORDER BY d.status;

SELECT
    'daily_digest_detail' AS section,
    d.digest_date,
    d.status,
    jsonb_typeof(d.event_document) AS event_document_type,
    jsonb_array_length(
        CASE
            WHEN jsonb_typeof(d.event_document->'matters') = 'array'
            THEN d.event_document->'matters'
            ELSE '[]'::jsonb
        END
    ) AS matter_count,
    d.event_model_info,
    d.updated_at
FROM review_daily_digests d
WHERE d.review_task_id = :'task_id'::uuid
ORDER BY d.digest_date;

SELECT
    'llm_call_log' AS section,
    l.created_at,
    l.step_name,
    l.status,
    l.model_name,
    l.duration_ms,
    l.prompt_tokens,
    l.completion_tokens,
    l.error_type,
    l.request_id,
    l.chain_id
FROM llm_call_logs l
WHERE l.review_task_id = :'task_id'::uuid
   OR (
        l.step_name = 'review_event_organize'
        AND l.created_at >= (
            SELECT COALESCE(started_at, created_at) - INTERVAL '10 minutes'
            FROM review_tasks
            WHERE id = :'task_id'::uuid
        )
        AND l.created_at <= (
            SELECT COALESCE(completed_at, CURRENT_TIMESTAMP) + INTERVAL '10 minutes'
            FROM review_tasks
            WHERE id = :'task_id'::uuid
        )
      )
ORDER BY l.created_at;

-- LangGraph 使用 task_id 作为 thread_id。以下查询只统计 checkpoint，
-- 不读取模型正文，避免诊断输出过大。
SELECT
    'checkpoint_summary' AS section,
    COUNT(*) AS checkpoint_count,
    MIN(checkpoint_id) AS first_checkpoint_id,
    MAX(checkpoint_id) AS last_checkpoint_id
FROM checkpoints
WHERE thread_id = :'task_id';

SELECT
    'checkpoint_writes_summary' AS section,
    COUNT(*) AS checkpoint_write_count,
    COUNT(DISTINCT checkpoint_id) AS checkpoint_count,
    MIN(task_id) AS first_node_task_id,
    MAX(task_id) AS last_node_task_id
FROM checkpoint_writes
WHERE thread_id = :'task_id';

ROLLBACK;
