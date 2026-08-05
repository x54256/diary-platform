-- 行动项与日记事件的关联（行动项生成时固化，不回填存量）。

CREATE TABLE IF NOT EXISTS diary_action_event_links (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    action_item_id UUID NOT NULL REFERENCES diary_action_items(id) ON DELETE CASCADE,
    diary_event_id UUID NOT NULL REFERENCES diary_events(id) ON DELETE CASCADE,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (action_item_id, diary_event_id)
);

CREATE INDEX IF NOT EXISTS ix_diary_action_event_links_event
    ON diary_action_event_links(diary_event_id);
