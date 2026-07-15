-- 002_analysis_pipeline.sql
-- 分析阶段数据模型变更

-- 1. diaries 表 status 枚举新增 analyzed
ALTER TYPE diarystatus ADD VALUE 'analyzed';

-- 2. organize_tasks 表新增 task_type 字段
ALTER TABLE organize_tasks ADD COLUMN task_type VARCHAR(20) DEFAULT 'organize';

-- 3. 新建 diary_analysis 表
CREATE TABLE diary_analysis (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES organize_tasks(id),
    diary_organized_id UUID NOT NULL UNIQUE REFERENCES diary_organized(id),
    mood VARCHAR(50),
    emotion_analysis TEXT,
    behavior_analysis TEXT,
    focus_analysis TEXT,
    cognitive_calibration TEXT,
    actionable_suggestions TEXT,
    analyzed_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 4. tags 表新增 type 字段
ALTER TABLE tags ADD COLUMN type VARCHAR(30);

-- 5. 新建 event_tags 关联表
CREATE TABLE event_tags (
    diary_event_id UUID NOT NULL REFERENCES diary_events(id),
    tag_id UUID NOT NULL REFERENCES tags(id),
    PRIMARY KEY (diary_event_id, tag_id)
);
