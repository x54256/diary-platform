ALTER TABLE schedule_tasks ADD COLUMN IF NOT EXISTS recurrence_month VARCHAR(2);
ALTER TABLE diary_action_items ADD COLUMN IF NOT EXISTS recurrence_month INTEGER;
UPDATE schedule_tasks
SET recurrence_month = EXTRACT(MONTH FROM start_date)::text
WHERE recurrence_type = 'YEARLY' AND recurrence_month IS NULL;
UPDATE diary_action_items
SET recurrence_month = EXTRACT(MONTH FROM start_date)::integer
WHERE recurrence_type = 'YEARLY' AND recurrence_month IS NULL;
