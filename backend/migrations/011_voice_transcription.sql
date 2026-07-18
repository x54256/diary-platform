CREATE TABLE IF NOT EXISTS transcription_batches (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id),
    diary_date DATE,
    base_text TEXT,
    status VARCHAR(30) NOT NULL DEFAULT 'COLLECTING',
    diary_id UUID UNIQUE REFERENCES diaries(id),
    error_message TEXT,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    expires_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS transcription_items (
    id UUID PRIMARY KEY,
    batch_id UUID NOT NULL REFERENCES transcription_batches(id) ON DELETE CASCADE,
    sort_order INTEGER NOT NULL,
    original_filename VARCHAR(255) NOT NULL,
    content_type VARCHAR(100) NOT NULL,
    file_size BIGINT NOT NULL DEFAULT 0,
    storage_key TEXT,
    status VARCHAR(30) NOT NULL DEFAULT 'UPLOADING',
    provider_task_id VARCHAR(100) UNIQUE,
    transcript_text TEXT,
    provider_request_id VARCHAR(100),
    error_code VARCHAR(100),
    error_message TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (batch_id, sort_order)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_transcription_active_user_date
ON transcription_batches (user_id, diary_date)
WHERE status IN ('QUEUED', 'PROCESSING', 'PARTIAL_FAILED', 'FINALIZING');

CREATE INDEX IF NOT EXISTS ix_transcription_batches_status_updated
ON transcription_batches (status, updated_at);
CREATE INDEX IF NOT EXISTS ix_transcription_batches_expires
ON transcription_batches (expires_at) WHERE status = 'PARTIAL_FAILED';
CREATE INDEX IF NOT EXISTS ix_transcription_items_batch_status
ON transcription_items (batch_id, status, sort_order);
