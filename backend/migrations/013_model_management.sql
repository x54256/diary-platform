-- 管理端 AI 模型管理。

CREATE TABLE IF NOT EXISTS model_catalog (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_type VARCHAR(20) NOT NULL,
    provider_name VARCHAR(100) NOT NULL,
    model_name VARCHAR(200) NOT NULL UNIQUE,
    ability_tier VARCHAR(100) NOT NULL,
    ability_category VARCHAR(50) NOT NULL,
    original_category VARCHAR(100),
    core_features TEXT,
    scenarios TEXT,
    score DOUBLE PRECISION,
    score_label VARCHAR(50),
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    is_custom BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_model_catalog_filters
    ON model_catalog(model_type, ability_tier, ability_category, enabled);

CREATE TABLE IF NOT EXISTS api_channels (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL UNIQUE,
    api_base_url VARCHAR(500) NOT NULL,
    api_key_encrypted TEXT,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS channel_models (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    channel_id UUID NOT NULL REFERENCES api_channels(id) ON DELETE CASCADE,
    model_id UUID NOT NULL REFERENCES model_catalog(id) ON DELETE CASCADE,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_channel_models_channel_model UNIQUE (channel_id, model_id)
);

CREATE INDEX IF NOT EXISTS idx_channel_models_channel_enabled
    ON channel_models(channel_id, enabled);

CREATE INDEX IF NOT EXISTS idx_channel_models_model_enabled
    ON channel_models(model_id, enabled);

ALTER TABLE channel_models DROP COLUMN IF EXISTS api_model_name;
ALTER TABLE channel_models DROP COLUMN IF EXISTS protocol;

UPDATE model_catalog
SET ability_category = CASE
    WHEN model_name ILIKE '%realtime%' THEN '实时语音识别'
    ELSE '录音文件识别'
END
WHERE model_type = 'asr'
  AND ability_category = '语音识别';

CREATE TABLE IF NOT EXISTS model_settings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    setting_key VARCHAR(30) NOT NULL UNIQUE,
    channel_model_id UUID NOT NULL REFERENCES channel_models(id),
    updated_by UUID REFERENCES users(id),
    updated_at TIMESTAMP DEFAULT NOW()
);
