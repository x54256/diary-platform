"""SQLite 隔离验证查询归属、来源解析、只读保护和快照；不访问项目数据库。"""

import contextlib
from datetime import date
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import create_engine, text

from export_events import (ExportError, digest, export_source, json_array, list_diaries,
                           main, read_connection, write_run)


class ExportTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        self.user, self.diary, self.org, self.event = [str(uuid4()) for _ in range(4)]
        with self.engine.begin() as db:
            for ddl in (
                "CREATE TABLE users (id TEXT PRIMARY KEY, username TEXT UNIQUE)",
                "CREATE TABLE diaries (id TEXT PRIMARY KEY, user_id TEXT, diary_date DATE, "
                "status TEXT, is_dirty BOOLEAN, content_revision INTEGER, deleted_at TEXT)",
                "CREATE TABLE diary_organized (id TEXT PRIMARY KEY, diary_id TEXT, "
                "source_content_revision INTEGER, structured_revision INTEGER)",
                "CREATE TABLE diary_events (id TEXT PRIMARY KEY, diary_organized_id TEXT, "
                "event_title TEXT, body TEXT, feeling TEXT, reflection TEXT, sort_order INTEGER, "
                "ai_importance TEXT, user_importance TEXT, updated_at TEXT)",
            ):
                db.execute(text(ddl))
            db.execute(text("INSERT INTO users VALUES (:id, 'owner')"), {"id": self.user})
            db.execute(text("INSERT INTO users VALUES (:id, 'other')"), {"id": str(uuid4())})
            db.execute(text("INSERT INTO diaries VALUES (:id, :user, '2026-09-09', "
                            "'organized', 0, 2, NULL)"), {"id": self.diary, "user": self.user})
            db.execute(text("INSERT INTO diary_organized VALUES (:id, :diary, 2, 3)"),
                       {"id": self.org, "diary": self.diary})
            self.add_event(db, self.event, "第二件事", 2, "MEDIUM", "LOW")
            self.earlier = str(uuid4())
            self.add_event(db, self.earlier, "第一件事", 1, "HIGH", None)

    def tearDown(self):
        self.engine.dispose()

    def add_event(self, db, event_id, title, order, ai, user):
        db.execute(text("INSERT INTO diary_events VALUES (:id, :org, :title, :body, :feeling, "
                        ":reflection, :sort, :ai, :user, '2026-09-10 12:00:00')"),
                   {"id": event_id, "org": self.org, "title": title,
                    "body": json.dumps(["第一段。", "第二段。"], ensure_ascii=False),
                    "feeling": '["有点高兴。"]', "reflection": None,
                    "sort": order, "ai": ai, "user": user})

    def export(self, db, **kwargs):
        return export_source(db, "owner", diary_id=self.diary, **kwargs)

    def test_owner_deleted_and_ambiguous_date_are_not_silently_selected(self):
        with self.engine.begin() as db:
            self.assertEqual(list_diaries(db, "owner", diary_date=date(2026, 9, 9))["match_count"], 1)
            self.assertEqual(list_diaries(db, "other", diary_id=self.diary)["match_count"], 0)
            with self.assertRaises(ExportError):
                list_diaries(db, "owner' OR 1=1 --", diary_id=self.diary)
            db.execute(text("INSERT INTO diaries VALUES (:id, :user, '2026-09-09', "
                            "'organized', 0, 1, NULL)"), {"id": str(uuid4()), "user": self.user})
            with self.assertRaisesRegex(ExportError, "多篇"):
                export_source(db, "owner", diary_date=date(2026, 9, 9))
            db.execute(text("UPDATE diaries SET deleted_at = '2026-10-21' WHERE id = :id"),
                       {"id": self.diary})
            with self.assertRaisesRegex(ExportError, "未找到"):
                self.export(db)

    def test_json_content_order_and_all_events_without_importance_metadata(self):
        with self.engine.connect() as db:
            source = self.export(db)
            self.assertEqual([e["event_id"] for e in source["events"]], [self.earlier, self.event])
            self.assertEqual(source["events"][0]["body"], ["第一段。", "第二段。"])
            self.assertEqual(source["events"][0]["reflection"], [])
            self.assertEqual(source["excluded_events"], [])
            self.assertEqual(source["selection"], {"event_ids": []})
            for event in source["events"]:
                self.assertFalse(any("importance" in key for key in event))

    def test_missing_or_changed_importance_does_not_change_export(self):
        with self.engine.begin() as db:
            before = self.export(db)
            db.execute(text("UPDATE diary_events SET ai_importance=NULL, user_importance=NULL"))
            self.assertEqual(self.export(db), before)
            db.execute(text("UPDATE diary_events SET ai_importance='LOW', user_importance='LOW'"))
            self.assertEqual(self.export(db), before)

    def test_event_selection_rejects_unknown_or_foreign_id(self):
        with self.engine.connect() as db:
            self.assertEqual(len(self.export(db, event_ids=[self.event])["events"]), 1)
            with self.assertRaisesRegex(ExportError, "不属于"):
                self.export(db, event_ids=[str(uuid4())])

    def test_stale_or_missing_organized_source_stops(self):
        with self.engine.begin() as db:
            db.execute(text("UPDATE diaries SET is_dirty = 1"))
            with self.assertRaisesRegex(ExportError, "过期"):
                self.export(db)
            db.execute(text("UPDATE diaries SET is_dirty = 0, content_revision = 4"))
            with self.assertRaisesRegex(ExportError, "过期"):
                self.export(db)
            db.execute(text("DELETE FROM diary_organized"))
            with self.assertRaisesRegex(ExportError, "整理结果"):
                self.export(db)

    def test_array_parser_does_not_iterate_characters_or_accept_malformed_body(self):
        self.assertEqual(json_array('["一段"]', "正文", required=True), ["一段"])
        self.assertEqual(json_array(["一段"], "正文", required=True), ["一段"])
        for invalid in (None, '"字符串"', "不是 JSON", "{}", "[]", '[1]', '["  "]'):
            with self.subTest(invalid=invalid), self.assertRaises(ExportError):
                json_array(invalid, "正文", required=True)

    def test_read_transaction_refuses_mutation(self):
        from sqlalchemy.exc import OperationalError
        with read_connection(self.engine) as db:
            self.assertEqual(len(self.export(db)["events"]), 2)
            with self.assertRaises(OperationalError):
                db.execute(text("DELETE FROM diaries"))

    def test_separate_runs_and_tampered_source(self):
        with self.engine.connect() as db:
            source = self.export(db)
        with tempfile.TemporaryDirectory() as directory:
            first = write_run(source, directory)
            before = (first / "source.json").read_bytes()
            second = write_run(source, directory)
            self.assertNotEqual(first, second)
            self.assertEqual(before, (first / "source.json").read_bytes())
            stored = json.loads((second / "source.json").read_text())
            self.assertEqual(stored, source)
            self.assertEqual(stored["source_sha256"], digest(
                {k: v for k, v in stored.items() if k != "source_sha256"}))
            self.assertIn("有点高兴。", (second / "source.md").read_text())
            self.assertNotIn("重要性", (second / "source.md").read_text())
            source["events"][0]["body"].append("改过的内容")
            with self.assertRaisesRegex(ExportError, "指纹"):
                write_run(source, directory)

    def test_cli_does_not_echo_connection_error_credentials(self):
        stderr = io.StringIO()
        with patch("export_events.load_engine", side_effect=RuntimeError("secret-connection-value")), \
                contextlib.redirect_stderr(stderr):
            result = main(["find", "--username", "owner", "--date", "2026-09-09"])
        self.assertEqual(result, 1)
        self.assertNotIn("secret-connection-value", stderr.getvalue())
        self.assertIn("RuntimeError", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
