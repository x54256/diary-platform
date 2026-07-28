-- 支持一条划线多条评论，以及划线合并关系

ALTER TABLE diary_annotations
    ADD COLUMN IF NOT EXISTS merged_into_id UUID REFERENCES diary_annotations(id);

DROP INDEX IF EXISTS uq_diary_annotation_active_comment;

CREATE INDEX IF NOT EXISTS idx_diary_annotations_merged_into
    ON diary_annotations(merged_into_id);
