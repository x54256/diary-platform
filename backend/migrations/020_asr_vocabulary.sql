-- 用户在阿里云 ASR 侧的热词列表同步状态。

CREATE TABLE IF NOT EXISTS asr_vocabularies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    vocabulary_id VARCHAR(200),
    target_model VARCHAR(200),
    fingerprint VARCHAR(64),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

ALTER TABLE transcription_batches
    ADD COLUMN IF NOT EXISTS hotword_vocabulary_id VARCHAR(200);

ALTER TABLE transcription_batches
    ADD COLUMN IF NOT EXISTS hotword_fingerprint VARCHAR(64);
