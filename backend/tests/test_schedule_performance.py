import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from routers.schedules import list_schedules


class ScheduleQueryPerformanceTest(unittest.TestCase):
    def test_list_does_not_generate_occurrences_on_read(self):
        db = MagicMock()
        query = db.query.return_value
        query.filter.return_value.order_by.return_value.all.return_value = []

        with patch("routers.schedules.ensure_occurrences", side_effect=AssertionError):
            list_schedules(date(2026, 7, 19), date(2026, 7, 25), db, SimpleNamespace(id="user"))


if __name__ == "__main__":
    unittest.main()
