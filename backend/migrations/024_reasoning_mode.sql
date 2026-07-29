-- 模型推理能力与渠道推理参数配置。

ALTER TABLE model_catalog
    ADD COLUMN IF NOT EXISTS reasoning_mode VARCHAR(20) NOT NULL DEFAULT 'unsupported';

ALTER TABLE api_channels
    ADD COLUMN IF NOT EXISTS thinkmode JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE model_catalog
    DROP COLUMN IF EXISTS supports_thinking;

ALTER TABLE model_catalog
    DROP COLUMN IF EXISTS thinking_config;

ALTER TABLE api_channels
    DROP COLUMN IF EXISTS think_config;

ALTER TABLE organize_pipeline_settings
    ADD COLUMN IF NOT EXISTS thinking_steps JSONB NOT NULL DEFAULT '{}'::jsonb;
