import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

from sqlalchemy.dialects.postgresql import dialect

from routers.schedules import ensure_occurrences_for_task


class ScheduleOccurrenceGenerationTest(unittest.TestCase):
    def test_missing_occurrences_are_inserted_idempotently(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []
        db.execute.return_value.rowcount = 1
        task = SimpleNamespace(
            id="task-id",
            user_id="user-id",
            title="午饭",
            is_all_day=False,
            start_date=date.today(),
            start_time=None,
            end_time=None,
            recurrence_type="NONE",
            recurrence_until=None,
            recurrence_count=None,
            interval="1",
            weekdays=None,
            month_day=None,
            nth_week=None,
            nth_weekday=None,
        )

        ensure_occurrences_for_task(db, task, date.today(), set(), set(), window_days=0)

        db.execute.assert_called_once()
        db.add_all.assert_not_called()
        statement = db.execute.call_args.args[0]
        sql = str(statement.compile(dialect=dialect()))
        self.assertIn("ON CONFLICT (task_id, scheduled_date) DO NOTHING", sql)


if __name__ == "__main__":
    unittest.main()
