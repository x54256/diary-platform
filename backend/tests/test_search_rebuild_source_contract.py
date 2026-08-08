"""搜索索引重建任务的无数据库关键契约测试。"""

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SearchRebuildSourceContractTest(unittest.TestCase):
    def test_job_is_resumable_and_only_updates_changed_indexes(self):
        source = (ROOT / "services" / "search_rebuild_jobs.py").read_text()
        self.assertIn("recover_search_index_rebuild_jobs", source)
        self.assertIn('SearchIndexRebuildJob.status == "running"', source)
        self.assertIn("refresh_changed_event_search_indexes", source)
        self.assertIn("sync_event_embeddings(db, event_id)", source)
        self.assertIn("last_event_id", source)

    def test_daily_maintenance_uses_24_hour_windows_and_china_time(self):
        source = (ROOT / "services" / "search_rebuild_jobs.py").read_text()
        for required in ("timedelta(hours=24)", "Asia/Shanghai", "hour=6", "include_event_content", "include_analysis"):
            self.assertIn(required, source)

    def test_admin_route_requires_admin_and_validates_date_range(self):
        source = (ROOT / "routers" / "admin_search.py").read_text()
        self.assertIn("Depends(require_admin)", source)
        self.assertIn("start_date 不能晚于 end_date", source)
        self.assertIn("已有搜索索引重建任务正在执行", source)
