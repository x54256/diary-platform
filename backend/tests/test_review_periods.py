import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

from services.review_periods import (
    ReviewPeriodError,
    first_generation_time,
    period_bounds,
    recent_completed_periods,
)


TZ = ZoneInfo("Asia/Shanghai")


class ReviewPeriodTest(unittest.TestCase):
    def test_week_requires_monday_and_ends_sunday(self):
        period = period_bounds("WEEK", date(2026, 7, 27))
        self.assertEqual(period.end, date(2026, 8, 2))
        self.assertEqual(first_generation_time(period), datetime(2026, 8, 3, 2, tzinfo=TZ))
        with self.assertRaises(ReviewPeriodError):
            period_bounds("WEEK", date(2026, 7, 28))

    def test_month_waits_for_week_containing_month_end(self):
        period = period_bounds("MONTH", date(2026, 7, 1))
        self.assertEqual(period.end, date(2026, 7, 31))
        self.assertEqual(first_generation_time(period), datetime(2026, 8, 3, 2, tzinfo=TZ))

    def test_recent_periods_exclude_current_week_and_unready_month(self):
        now = datetime(2026, 8, 1, 12, tzinfo=TZ)
        weeks = recent_completed_periods("WEEK", now=now, limit=2)
        months = recent_completed_periods("MONTH", now=now, limit=2)
        self.assertEqual(weeks[0].start, date(2026, 7, 20))
        self.assertEqual(months[0].start, date(2026, 6, 1))


if __name__ == "__main__":
    unittest.main()
