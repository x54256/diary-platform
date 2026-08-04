-- 为已存在的数据库补充独立行动规划环节的模型覆盖配置。

INSERT INTO model_step_settings (id, step_key, thinking_enabled)
SELECT gen_random_uuid(), 'action_planning', TRUE
FROM model_settings AS setting
JOIN channel_models AS channel_model ON channel_model.id = setting.channel_model_id
WHERE setting.setting_key = 'analysis'
ON CONFLICT (step_key) DO NOTHING;
