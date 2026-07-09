-- 分析管线 V2：双层数组结构 + 事件级分析

-- 1. diary_analysis: 删除旧的扁平文本字段
ALTER TABLE diary_analysis DROP COLUMN IF EXISTS emotion_analysis;
ALTER TABLE diary_analysis DROP COLUMN IF EXISTS behavior_analysis;
ALTER TABLE diary_analysis DROP COLUMN IF EXISTS focus_analysis;
ALTER TABLE diary_analysis DROP COLUMN IF EXISTS cognitive_calibration;
ALTER TABLE diary_analysis DROP COLUMN IF EXISTS actionable_suggestions;

-- 2. diary_analysis: 新增 JSON 数组字段
ALTER TABLE diary_analysis ADD COLUMN emotion_analyses TEXT;
ALTER TABLE diary_analysis ADD COLUMN behavior_decision_analyses TEXT;
ALTER TABLE diary_analysis ADD COLUMN self_understanding_analyses TEXT;
ALTER TABLE diary_analysis ADD COLUMN action_suggestions TEXT;
ALTER TABLE diary_analysis ADD COLUMN cognitive_calibration_analyses TEXT;
ALTER TABLE diary_analysis ADD COLUMN question_answers TEXT;
ALTER TABLE diary_analysis ADD COLUMN cognitive_enhancements TEXT;

-- 3. diary_events: 新增事件级分析字段
ALTER TABLE diary_events ADD COLUMN IF NOT EXISTS analysis TEXT;

-- 4. 清理旧分析数据（旧格式不兼容新结构）
DELETE FROM diary_analysis;
