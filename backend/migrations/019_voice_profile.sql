-- 用户热词与人物关系管理。

CREATE TABLE IF NOT EXISTS hot_words (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    text VARCHAR(100) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_hot_words_user_text UNIQUE (user_id, text)
);

CREATE INDEX IF NOT EXISTS ix_hot_words_user_created
ON hot_words(user_id, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS uq_hot_words_user_text_case_insensitive
ON hot_words(user_id, LOWER(text));

CREATE TABLE IF NOT EXISTS person_relations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    common_names JSONB NOT NULL DEFAULT '[]'::jsonb,
    gender VARCHAR(20) NOT NULL DEFAULT 'unknown',
    relation VARCHAR(100) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_person_relations_user_name UNIQUE (user_id, name)
);

CREATE INDEX IF NOT EXISTS ix_person_relations_user_created
ON person_relations(user_id, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS uq_person_relations_user_name_case_insensitive
ON person_relations(user_id, LOWER(name));
