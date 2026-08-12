DROP INDEX uq_knowledge_tasks_source_active;

ALTER TABLE knowledge_tasks
    DROP COLUMN source_analysis_run_id;

CREATE UNIQUE INDEX uq_knowledge_tasks_source_active
    ON knowledge_tasks(diary_id, source_structured_revision)
    WHERE status IN ('QUEUED','RUNNING');

ALTER TABLE knowledge_deposits
    DROP COLUMN source_analysis_run_id;
