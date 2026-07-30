CREATE TABLE IF NOT EXISTS favorites (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    diary_id UUID REFERENCES diaries(id) ON DELETE CASCADE,
    event_id UUID REFERENCES diary_events(id) ON DELETE CASCADE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_favorites_exactly_one_target CHECK (
        (diary_id IS NOT NULL AND event_id IS NULL)
        OR (diary_id IS NULL AND event_id IS NOT NULL)
    ),
    CONSTRAINT uq_favorites_user_diary UNIQUE (user_id, diary_id),
    CONSTRAINT uq_favorites_user_event UNIQUE (user_id, event_id)
);

CREATE INDEX IF NOT EXISTS ix_favorites_user_created_at ON favorites(user_id, created_at DESC);
