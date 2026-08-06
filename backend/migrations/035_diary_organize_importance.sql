-- 将事件重要性评定前移到日记整理阶段。

ALTER TABLE diary_events DROP CONSTRAINT IF EXISTS ck_diary_events_importance_origin;
ALTER TABLE diary_events ADD CONSTRAINT ck_diary_events_importance_origin
    CHECK (importance_origin IS NULL OR importance_origin IN ('DIARY_ORGANIZE', 'DIARY_ANALYSIS', 'LEGACY_BACKFILL'));
