-- 定时索引按事件内容和分析内容各自的最后修改时间判断 24 小时静默窗口。
ALTER TABLE diary_events ADD COLUMN updated_at TIMESTAMPTZ;
UPDATE diary_events SET updated_at = created_at WHERE updated_at IS NULL;
ALTER TABLE diary_events ALTER COLUMN updated_at SET NOT NULL;
ALTER TABLE diary_events ALTER COLUMN updated_at SET DEFAULT now();

ALTER TABLE analysis_items ADD COLUMN updated_at TIMESTAMPTZ;
UPDATE analysis_items SET updated_at = created_at WHERE updated_at IS NULL;
ALTER TABLE analysis_items ALTER COLUMN updated_at SET NOT NULL;
ALTER TABLE analysis_items ALTER COLUMN updated_at SET DEFAULT now();

CREATE INDEX ix_diary_events_updated_at ON diary_events(updated_at);
CREATE INDEX ix_analysis_items_event_updated_at ON analysis_items(event_id, updated_at);
