-- 日记 AI 处理流水线重构迁移脚本
-- 2026-07-06

-- DiaryOrganized 新增字段
ALTER TABLE diary_organized ADD COLUMN IF NOT EXISTS task_id UUID REFERENCES organize_tasks(id);
ALTER TABLE diary_organized ADD COLUMN IF NOT EXISTS introduction TEXT;
ALTER TABLE diary_organized ADD COLUMN IF NOT EXISTS trivia TEXT;
ALTER TABLE diary_organized ADD COLUMN IF NOT EXISTS plans TEXT;

-- DiaryEvent 新增标签
ALTER TABLE diary_events ADD COLUMN IF NOT EXISTS event_tags TEXT;

-- DiaryCheckLog: 移除旧字段，新增字段
ALTER TABLE diary_check_logs DROP COLUMN IF EXISTS fix;
ALTER TABLE diary_check_logs ADD COLUMN IF NOT EXISTS target VARCHAR(200);
ALTER TABLE diary_check_logs ADD COLUMN IF NOT EXISTS reason TEXT;
ALTER TABLE diary_check_logs ADD COLUMN IF NOT EXISTS before TEXT;
ALTER TABLE diary_check_logs ADD COLUMN IF NOT EXISTS after TEXT;

-- 新建清洗审核日志表
CREATE TABLE IF NOT EXISTS diary_clean_check_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    diary_organized_id UUID NOT NULL REFERENCES diary_organized(id) ON DELETE CASCADE,
    issue TEXT,
    before TEXT,
    after TEXT,
    reason TEXT,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 补充：如果表已存在但缺少列，手动补加
ALTER TABLE diary_clean_check_logs ADD COLUMN IF NOT EXISTS before TEXT;
ALTER TABLE diary_clean_check_logs ADD COLUMN IF NOT EXISTS after TEXT;
ALTER TABLE diary_clean_check_logs ADD COLUMN IF NOT EXISTS reason TEXT;
