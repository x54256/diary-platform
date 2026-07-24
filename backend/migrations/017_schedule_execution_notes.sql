ALTER TABLE schedule_occurrences ADD COLUMN IF NOT EXISTS execution_note TEXT;
UPDATE schedule_occurrences
SET execution_note = overdue_reason
WHERE execution_note IS NULL AND overdue_reason IS NOT NULL;
