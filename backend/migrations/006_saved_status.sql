-- 合并草稿/发布状态为 saved
-- 旧状态链：draft -> published -> organized -> analyzed
-- 新状态链：saved -> organized -> analyzed

ALTER TYPE diarystatus RENAME TO diarystatus_old;

CREATE TYPE diarystatus AS ENUM ('saved', 'organized', 'analyzed');

ALTER TABLE diaries ALTER COLUMN status DROP DEFAULT;

ALTER TABLE diaries
    ALTER COLUMN status TYPE diarystatus
    USING (
        CASE
            WHEN status::text IN ('draft', 'published') THEN 'saved'
            ELSE status::text
        END
    )::diarystatus;

ALTER TABLE diaries ALTER COLUMN status SET DEFAULT 'saved';

DROP TYPE diarystatus_old;
