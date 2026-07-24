CREATE TABLE IF NOT EXISTS schedule_holiday_years (
    year INTEGER PRIMARY KEY,
    is_available BOOLEAN NOT NULL DEFAULT FALSE,
    workdays TEXT NOT NULL DEFAULT '[]',
    restdays TEXT NOT NULL DEFAULT '[]',
    fetched_at TIMESTAMP NOT NULL DEFAULT NOW()
);

ALTER TABLE schedule_occurrences
    ADD COLUMN IF NOT EXISTS manually_modified BOOLEAN NOT NULL DEFAULT FALSE;
