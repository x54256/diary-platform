-- 破坏性迁移：语音临时文件从本地路径切换到 MinIO object key。
-- 旧的本地临时音频不再兼容，迁移时直接删除未完成的语音转写批次。

DELETE FROM transcription_batches
WHERE status IN ('COLLECTING', 'QUEUED', 'PROCESSING', 'PARTIAL_FAILED', 'FINALIZING', 'CANCELLED', 'EXPIRED');

ALTER TABLE transcription_items
DROP COLUMN IF EXISTS storage_path;

ALTER TABLE transcription_items
ADD COLUMN IF NOT EXISTS storage_key TEXT;

ALTER TABLE transcription_items
DROP COLUMN IF EXISTS access_token_hash;

ALTER TABLE transcription_items
DROP COLUMN IF EXISTS access_expires_at;
