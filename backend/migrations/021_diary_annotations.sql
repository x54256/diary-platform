-- 日记正文与 AI 分析内容的划线批注、评论

CREATE TABLE IF NOT EXISTS diary_annotations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    diary_id UUID NOT NULL REFERENCES diaries(id),
    target_type VARCHAR(30) NOT NULL,
    event_id UUID REFERENCES diary_events(id),
    field_name VARCHAR(30),
    analysis_item_id UUID REFERENCES analysis_items(id),
    start_paragraph INTEGER NOT NULL DEFAULT 0 CHECK (start_paragraph >= 0),
    start_offset INTEGER NOT NULL CHECK (start_offset >= 0),
    end_paragraph INTEGER NOT NULL DEFAULT 0 CHECK (end_paragraph >= 0),
    end_offset INTEGER NOT NULL CHECK (end_offset >= 0),
    selected_text TEXT NOT NULL,
    context_before TEXT,
    context_after TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP,
    deleted_by UUID REFERENCES users(id),
    deleted_reason VARCHAR(30),
    CONSTRAINT ck_diary_annotation_target CHECK (
        (target_type = 'EVENT_BODY' AND event_id IS NOT NULL AND field_name = 'body' AND analysis_item_id IS NULL)
        OR (target_type = 'EVENT_FEELING' AND event_id IS NOT NULL AND field_name = 'feeling' AND analysis_item_id IS NULL)
        OR (target_type = 'EVENT_REFLECTION' AND event_id IS NOT NULL AND field_name = 'reflection' AND analysis_item_id IS NULL)
        OR (target_type = 'ANALYSIS_ITEM' AND event_id IS NULL AND field_name IS NULL AND analysis_item_id IS NOT NULL)
    ),
    CONSTRAINT ck_diary_annotation_range CHECK (
        end_paragraph > start_paragraph
        OR (end_paragraph = start_paragraph AND end_offset > start_offset)
    )
);

CREATE TABLE IF NOT EXISTS diary_annotation_comments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    annotation_id UUID NOT NULL REFERENCES diary_annotations(id),
    content TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP,
    deleted_by UUID REFERENCES users(id),
    deleted_reason VARCHAR(30)
);

CREATE INDEX IF NOT EXISTS idx_diary_annotations_diary_active
    ON diary_annotations(diary_id, deleted_at, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_diary_annotations_event_field
    ON diary_annotations(event_id, field_name, deleted_at);

CREATE INDEX IF NOT EXISTS idx_diary_annotations_analysis_item
    ON diary_annotations(analysis_item_id, deleted_at);
