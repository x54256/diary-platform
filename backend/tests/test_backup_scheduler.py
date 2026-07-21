"""定时备份调度规则测试。"""

import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from config import settings
from services.backup_scheduler import (
    next_scheduled_run,
    parse_schedule_time,
    run_scheduled_backup_with_retry,
)


class BackupScheduleRuleTest(unittest.TestCase):
    def test_schedule_time_is_configurable(self):
        self.assertEqual(parse_schedule_time("23:45").hour, 23)
        self.assertEqual(parse_schedule_time("23:45").minute, 45)

    def test_next_run_does_not_make_startup_catch_up(self):
        with patch.object(settings, "BACKUP_SCHEDULE_TIME", "02:00"), patch.object(
            settings, "BACKUP_SCHEDULE_TIMEZONE", "Asia/Shanghai"
        ):
            now = datetime(2026, 7, 21, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
            next_run = next_scheduled_run(now)

        self.assertEqual(next_run.date().isoformat(), "2026-07-22")
        self.assertEqual(next_run.hour, 2)


class BackupRetryTest(unittest.IsolatedAsyncioTestCase):
    async def test_failed_backup_is_retried_once(self):
        with patch(
            "services.backup_scheduler._create_scheduled_export",
            side_effect=[RuntimeError("first failure"), None],
        ) as create_export:
            await run_scheduled_backup_with_retry()

        self.assertEqual(create_export.call_count, 2)


if __name__ == "__main__":
    unittest.main()
