-- 反馈复制状态。
-- 已执行 007 的环境需要补充这两个字段；新环境在 007 中已包含字段定义。

ALTER TABLE analysis_feedback
    ADD COLUMN IF NOT EXISTS is_inherited BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE analysis_feedback
    ADD COLUMN IF NOT EXISTS source_feedback_id UUID REFERENCES analysis_feedback(id) ON DELETE SET NULL;
