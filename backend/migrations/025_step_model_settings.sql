-- 业务用途默认思考模式与环节级模型/思考覆盖。

ALTER TABLE model_settings
    ADD COLUMN IF NOT EXISTS thinking_enabled BOOLEAN;

UPDATE model_settings AS setting
SET thinking_enabled = CASE
    WHEN setting.setting_key = 'transcription' THEN NULL
    WHEN model.reasoning_mode = 'always_on' THEN TRUE
    ELSE FALSE
END
FROM channel_models AS channel_model
JOIN model_catalog AS model ON model.id = channel_model.model_id
WHERE setting.channel_model_id = channel_model.id
  AND setting.thinking_enabled IS NULL;

CREATE TABLE IF NOT EXISTS model_step_settings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    step_key VARCHAR(50) NOT NULL UNIQUE,
    channel_model_id UUID REFERENCES channel_models(id),
    thinking_enabled BOOLEAN,
    updated_by UUID REFERENCES users(id),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_model_step_settings_channel_model
    ON model_step_settings(channel_model_id);

INSERT INTO model_step_settings (id, step_key, thinking_enabled)
SELECT gen_random_uuid() AS id,defaults.step_key, CASE
                              WHEN model.reasoning_mode = 'unsupported' THEN FALSE
                              WHEN model.reasoning_mode = 'always_on' THEN TRUE
                              ELSE COALESCE(
                                      (SELECT (thinking_steps ->> defaults.step_key)::BOOLEAN FROM organize_pipeline_settings WHERE id = 1),
                                      defaults.default_value
                                   )
    END
FROM (
         VALUES
             ('text_clean', 'organize', FALSE),
             ('clean_check', 'organize', FALSE),
             ('event_organize', 'organize', TRUE),
             ('template_fill', 'organize', FALSE),
             ('content_check', 'organize', FALSE),
             ('mood_tag_extract', 'analysis', FALSE),
             ('core_analysis', 'analysis', TRUE),
             ('cognition_analysis', 'analysis', TRUE),
             ('action_planning', 'analysis', TRUE),
             ('feedback_core_analysis', 'analysis', TRUE),
             ('feedback_cognition_analysis', 'analysis', TRUE)
     ) AS defaults(step_key, setting_key, default_value)
         JOIN model_settings AS setting ON setting.setting_key = defaults.setting_key
         JOIN channel_models AS channel_model ON channel_model.id = setting.channel_model_id
         JOIN model_catalog AS model ON model.id = channel_model.model_id
ON CONFLICT (step_key) DO NOTHING;



ALTER TABLE organize_pipeline_settings
    DROP COLUMN IF EXISTS thinking_steps;
