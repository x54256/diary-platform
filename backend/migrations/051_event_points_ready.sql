-- 独立保存事件要点及向量，不把整日处理标记为已发布。
ALTER TABLE graph_runs DROP CONSTRAINT ck_graph_run_status;
ALTER TABLE graph_runs ADD CONSTRAINT ck_graph_run_status
CHECK (status IN ('QUEUED','RUNNING','FAILED','POINTS_READY','PUBLISHED','OBSOLETE','SKIPPED'));
