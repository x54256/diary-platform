-- 分析历史、分析类型块反馈、日记软删除

ALTER TABLE diaries ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP;
ALTER TABLE diaries ADD COLUMN IF NOT EXISTS deleted_by UUID REFERENCES users(id);

CREATE TABLE IF NOT EXISTS analysis_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    diary_id UUID NOT NULL REFERENCES diaries(id),
    diary_organized_id UUID NOT NULL REFERENCES diary_organized(id),
    task_id UUID REFERENCES organize_tasks(id),
    mood VARCHAR(50),
    status VARCHAR(20) NOT NULL DEFAULT 'CURRENT',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_analysis_runs_current_diary
    ON analysis_runs(diary_id)
    WHERE status = 'CURRENT';

CREATE INDEX IF NOT EXISTS idx_analysis_runs_diary_status
    ON analysis_runs(diary_id, status);

CREATE TABLE IF NOT EXISTS analysis_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    analysis_run_id UUID NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
    scope VARCHAR(20) NOT NULL,
    event_id UUID REFERENCES diary_events(id),
    analysis_type VARCHAR(50) NOT NULL,
    content TEXT NOT NULL,
    question TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_analysis_items_run_scope_type
    ON analysis_items(analysis_run_id, scope, event_id, analysis_type, sort_order);

CREATE TABLE IF NOT EXISTS analysis_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    analysis_run_id UUID NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id),
    scope VARCHAR(20) NOT NULL,
    event_id UUID REFERENCES diary_events(id),
    analysis_type VARCHAR(50) NOT NULL,
    rating INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 5),
    comment TEXT,
    is_inherited BOOLEAN NOT NULL DEFAULT FALSE,
    source_feedback_id UUID REFERENCES analysis_feedback(id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_analysis_feedback_target
    ON analysis_feedback (
        user_id,
        analysis_run_id,
        scope,
        COALESCE(event_id, '00000000-0000-0000-0000-000000000000'::uuid),
        analysis_type
    );

CREATE INDEX IF NOT EXISTS idx_analysis_feedback_run
    ON analysis_feedback(analysis_run_id);

-- 迁移当前仍存在的日记级分析结果。
INSERT INTO analysis_runs (
    id,
    diary_id,
    diary_organized_id,
    task_id,
    mood,
    status,
    created_at,
    updated_at
)
SELECT
    da.id,
    dorg.diary_id,
    da.diary_organized_id,
    da.task_id,
    da.mood,
    'CURRENT',
    COALESCE(da.analyzed_at, da.updated_at, CURRENT_TIMESTAMP),
    COALESCE(da.updated_at, da.analyzed_at, CURRENT_TIMESTAMP)
FROM diary_analysis da
JOIN diary_organized dorg ON dorg.id = da.diary_organized_id
ON CONFLICT (id) DO NOTHING;

INSERT INTO analysis_items (id, analysis_run_id, scope, event_id, analysis_type, content, sort_order, created_at)
SELECT gen_random_uuid(), da.id, 'DIARY', NULL, src.analysis_type, item.value, item.ordinality - 1, CURRENT_TIMESTAMP
FROM diary_analysis da
JOIN LATERAL (
    VALUES
        ('EMOTION', da.emotion_analyses),
        ('BEHAVIOR_DECISION', da.behavior_decision_analyses),
        ('SELF_UNDERSTANDING', da.self_understanding_analyses),
        ('ACTION_SUGGESTION', da.action_suggestions),
        ('COGNITIVE_CALIBRATION', da.cognitive_calibration_analyses),
        ('COGNITIVE_ENHANCEMENT', da.cognitive_enhancements)
) AS src(analysis_type, raw_json) ON TRUE
JOIN LATERAL jsonb_array_elements_text(COALESCE(NULLIF(src.raw_json, ''), '[]')::jsonb)
    WITH ORDINALITY AS item(value, ordinality) ON TRUE
WHERE NOT EXISTS (
    SELECT 1
    FROM analysis_items existing
    WHERE existing.analysis_run_id = da.id
      AND existing.scope = 'DIARY'
      AND existing.event_id IS NULL
      AND existing.analysis_type = src.analysis_type
      AND existing.sort_order = item.ordinality - 1
);

-- 迁移当前仍存在的事件级分析结果。
INSERT INTO analysis_items (id, analysis_run_id, scope, event_id, analysis_type, content, sort_order, created_at)
SELECT gen_random_uuid(), ar.id, 'EVENT', de.id, src.analysis_type, item.value, item.ordinality - 1, CURRENT_TIMESTAMP
FROM diary_events de
JOIN diary_organized dorg ON dorg.id = de.diary_organized_id
JOIN analysis_runs ar ON ar.diary_organized_id = dorg.id AND ar.status = 'CURRENT'
JOIN LATERAL (
    VALUES
        ('EMOTION', de.analysis::jsonb -> 'emotion_analyses'),
        ('BEHAVIOR_DECISION', de.analysis::jsonb -> 'behavior_decision_analyses'),
        ('SELF_UNDERSTANDING', de.analysis::jsonb -> 'self_understanding_analyses'),
        ('ACTION_SUGGESTION', de.analysis::jsonb -> 'action_suggestions'),
        ('COGNITIVE_CALIBRATION', de.analysis::jsonb -> 'cognitive_calibration_analyses'),
        ('COGNITIVE_ENHANCEMENT', de.analysis::jsonb -> 'cognitive_enhancements')
) AS src(analysis_type, raw_json) ON de.analysis IS NOT NULL AND de.analysis <> ''
JOIN LATERAL jsonb_array_elements_text(COALESCE(src.raw_json, '[]'::jsonb))
    WITH ORDINALITY AS item(value, ordinality) ON TRUE
WHERE NOT EXISTS (
    SELECT 1
    FROM analysis_items existing
    WHERE existing.analysis_run_id = ar.id
      AND existing.scope = 'EVENT'
      AND existing.event_id = de.id
      AND existing.analysis_type = src.analysis_type
      AND existing.sort_order = item.ordinality - 1
);

INSERT INTO analysis_items (id, analysis_run_id, scope, event_id, analysis_type, content, question, sort_order, created_at)
SELECT gen_random_uuid(),
       ar.id,
       'EVENT',
       de.id,
       'QUESTION_ANSWER',
       COALESCE(item.value ->> 'answer', ''),
       item.value ->> 'question',
       item.ordinality - 1,
       CURRENT_TIMESTAMP
FROM diary_events de
JOIN diary_organized dorg ON dorg.id = de.diary_organized_id
JOIN analysis_runs ar ON ar.diary_organized_id = dorg.id AND ar.status = 'CURRENT'
JOIN LATERAL jsonb_array_elements(COALESCE(de.analysis::jsonb -> 'question_answers', '[]'::jsonb))
    WITH ORDINALITY AS item(value, ordinality) ON de.analysis IS NOT NULL AND de.analysis <> ''
WHERE COALESCE(item.value ->> 'answer', '') <> ''
  AND NOT EXISTS (
    SELECT 1
    FROM analysis_items existing
    WHERE existing.analysis_run_id = ar.id
      AND existing.scope = 'EVENT'
      AND existing.event_id = de.id
      AND existing.analysis_type = 'QUESTION_ANSWER'
      AND existing.sort_order = item.ordinality - 1
);
