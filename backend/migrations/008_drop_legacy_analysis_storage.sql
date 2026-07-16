-- 清理旧分析存储。
-- 执行前必须先执行 007_analysis_history_feedback.sql，确保旧数据已迁移到 analysis_runs / analysis_items。

ALTER TABLE diary_events DROP COLUMN IF EXISTS analysis;

DROP TABLE IF EXISTS diary_analysis;
