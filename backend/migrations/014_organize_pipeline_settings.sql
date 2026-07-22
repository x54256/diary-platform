-- 日记整理流水线审核环节开关。

CREATE TABLE IF NOT EXISTS organize_pipeline_settings (
    id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    clean_check_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    content_check_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    updated_by UUID REFERENCES users(id),
    updated_at TIMESTAMP DEFAULT NOW()
);

INSERT INTO organize_pipeline_settings (id)
VALUES (1)
ON CONFLICT (id) DO NOTHING;
