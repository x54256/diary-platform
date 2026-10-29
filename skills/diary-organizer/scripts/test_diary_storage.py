"""隔离验证转换、确认绑定及事务写入；不连接项目数据库。"""

import copy
import contextlib
import io
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from markdown_to_json import parse_markdown
from store_diary import find_diaries, load_source, load_target, main, make_packet, open_backend, persist_result, snapshot, verify_packet


SAMPLE = """背景。

## 事件：排查导出慢

检查了 SQL。

1. 测量查询。
2. 检查写文件。

### 感受

- 找到原因很开心。
- 仍有些累。

### 重要性

MEDIUM：找到了主要耗时环节。

## 琐事

- 买了牛奶。

## 后续计划

- 考虑明天再验证。
"""


class ConversionTest(unittest.TestCase):
    def test_complete_reference_example_is_importable(self):
        import re

        reference = (Path(__file__).resolve().parents[1] / "references/examples.md").read_text()
        section = reference.split("## 10. 完整可转换示例", 1)[1]
        markdown = re.search(r"```markdown\n(.*?)\n```", section, re.S).group(1)
        result = parse_markdown(markdown)
        self.assertEqual(result["events"][0]["importance"], "LOW")
        self.assertEqual(result["plans"], ["准备周六提交报销。"])

    def test_retains_paragraphs_steps_and_optional_fields(self):
        result = parse_markdown(SAMPLE)
        event = result["events"][0]
        self.assertEqual(event["body"], ["检查了 SQL。", "1. 测量查询。\n2. 检查写文件。"])
        self.assertEqual(event["feeling"], ["找到原因很开心。", "仍有些累。"])
        self.assertEqual(event["reflection"], [])
        self.assertEqual(result["plans"], ["考虑明天再验证。"])

    def test_rejects_ambiguous_or_incomplete_structure(self):
        for invalid in (
            SAMPLE.replace("MEDIUM：找到了主要耗时环节。", ""),
            SAMPLE.replace("## 琐事", "## 其他"),
            SAMPLE.replace("- 买了牛奶。", "买了牛奶。"),
            SAMPLE + "\n## 事件：后置事件\n正文。\n",
            SAMPLE.replace("### 感受", "### 感受\n\n### 感受"),
            "## 事件：空事件\n\n### 重要性\n\nLOW：没有影响。",
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                parse_markdown(invalid)

    def test_confirmation_detects_payload_and_file_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            markdown, notes = root / "整理稿.md", root / "澄清记录.md"
            markdown.write_text(SAMPLE, encoding="utf-8")
            notes.write_text("本次无需澄清。", encoding="utf-8")
            packet = make_packet(markdown, notes, {})
            verify_packet(packet, packet["confirmation_sha256"])
            changed = copy.deepcopy(packet)
            changed["result"]["events"][0]["title"] = "其他事件"
            with self.assertRaises(ValueError):
                verify_packet(changed)
            with self.assertRaises(ValueError):
                verify_packet(packet, "wrong")
            notes.write_text("新增确认。", encoding="utf-8")
            with self.assertRaises(ValueError):
                verify_packet(packet)


class StorageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        open_backend(Path(__file__).resolve().parents[3] / "backend")
        from database import Base
        from sqlalchemy import CheckConstraint, MetaData, DefaultClause, text
        from sqlalchemy.dialects.postgresql import JSONB, UUID
        from sqlalchemy.ext.compiler import compiles

        @compiles(JSONB, "sqlite")
        def sqlite_jsonb(type_, compiler, **kwargs):
            return "JSON"

        @compiles(UUID, "sqlite")
        def sqlite_uuid(type_, compiler, **kwargs):
            return "CHAR(32)"

        # 复制模型供 SQLite 隔离验证，不修改生产模型。去除 PG 专属索引与默认值类型转换。
        cls.metadata = MetaData()
        for table in Base.metadata.tables.values():
            clone = table.to_metadata(cls.metadata)
            clone.indexes.clear()
            if clone.name.startswith("graph_"):
                for constraint in list(clone.constraints):
                    if isinstance(constraint, CheckConstraint):
                        clone.constraints.remove(constraint)
            for column in clone.columns:
                if getattr(column.server_default, "arg", None) is not None and "gen_random_uuid()" in str(column.server_default.arg):
                    column.server_default = None
                if getattr(column.server_default, "arg", None) is not None and "::jsonb" in str(column.server_default.arg):
                    column.server_default = DefaultClause(text(str(column.server_default.arg).replace("::jsonb", "")))

    def setUp(self):
        from sqlalchemy import create_engine, event
        from sqlalchemy.orm import sessionmaker
        from models.user import User
        from models.diary import Diary

        self.engine = create_engine("sqlite://")

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, record):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.create_function("LEAST", 2, min, deterministic=True)
            connection.create_function("GREATEST", 2, max, deterministic=True)
            connection.create_function("BTRIM", 1, lambda value: value.strip() if value is not None else None, deterministic=True)
            connection.create_function("jsonb_typeof", 1, lambda value: "object" if isinstance(json.loads(value), dict) else "array", deterministic=True)

        self.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.user_id, self.diary_id = uuid4(), uuid4()
        with self.Session.begin() as db:
            db.add(User(id=self.user_id, username="isolated", password_encrypted="test-only"))
            db.flush()
            db.add(Diary(id=self.diary_id, user_id=self.user_id, original_text="测试原文",
                         diary_date=date(2026, 9, 29)))
        self.result = parse_markdown(SAMPLE)

    def test_api_roundtrip_uses_uploaded_cloud_files_and_original_confirmation(self):
        from config import settings
        from services.skill_worker import execute
        from models.diary import Diary, OrganizeTask
        cloud_md, cloud_notes, cloud_source = '/cloud/diary/整理稿.md', '/cloud/diary/澄清记录.md', '/cloud/diary/source.json'
        with patch('database.SessionLocal', self.Session), patch.object(settings, 'SKILL_API_USERNAME', 'isolated'):
            def call(action, params, files=None):
                return execute({'stage': 'organize', 'action': action, 'params': params, 'files': files or {}})
            exported = call('export', {'diary_id': str(self.diary_id), 'user_id': str(self.user_id)})['file']
            files = {cloud_md: SAMPLE, cloud_notes: '本次无需澄清。', cloud_source: json.dumps(exported, ensure_ascii=False)}
            packet = call('prepare', {'markdown': cloud_md, 'clarifications': cloud_notes, 'source': cloud_source}, files)['packet']
            self.assertEqual(packet['markdown']['path'], cloud_md)
            with self.Session() as db:
                self.assertEqual(db.query(OrganizeTask).count(), 0)
            with self.assertRaises(ValueError):
                call('save', {'packet': packet, 'write': True, 'confirmed_sha256': 'wrong'}, files)
            changed = {**files, cloud_notes: '新增澄清'}
            with self.assertRaises(ValueError):
                call('save', {'packet': packet, 'write': True, 'confirmed_sha256': packet['confirmation_sha256']}, changed)
            receipt = call('save', {'packet': packet, 'write': True, 'confirmed_sha256': packet['confirmation_sha256']}, files)
            self.assertEqual(receipt['events'], 1)
            with self.Session() as db:
                self.assertEqual(db.get(Diary, self.diary_id).status.value, 'organized')
            with self.assertRaises(ValueError):
                call('export', {'diary_id': str(self.diary_id), 'user_id': str(uuid4())})

    def review_source(self):
        from review_diary import export_current
        with self.Session.begin() as db:
            persist_result(db, self.target(db), self.result)
        with self.Session() as db:
            from models.diary import Diary
            return export_current(db, db.get(Diary, self.diary_id))

    def test_review_patch_preserves_ids_body_and_metadata_and_updates_revision(self):
        from review_diary import execute, compare
        from models.diary import Diary
        original = self.review_source()
        eid = original['events'][0]['event_id']
        changes = {'events': [{'event_id': eid, 'feeling': ['找到原因后轻松。', '剩余工作让我疲惫。']}], 'plans': ['先休息。']}
        with self.Session.begin() as db:
            packet = execute(db, 'prepare', {'exported': original, 'changes': changes})['packet']
        with self.Session.begin() as db:
            receipt = execute(db, 'save', {'packet': packet, 'write': True, 'confirmed_sha256': packet['confirmation_sha256']})
        current = receipt['source']
        self.assertEqual(current['events'][0]['event_id'], eid)
        self.assertEqual(current['events'][0]['body'], original['events'][0]['body'])
        self.assertEqual(current['events'][0]['reflection'], original['events'][0]['reflection'])
        self.assertEqual(current['events'][0]['feeling'], changes['events'][0]['feeling'])
        self.assertEqual(current['plans'], ['先休息。'])
        self.assertEqual(current['source']['structured_revision'], original['source']['structured_revision'] + 1)
        self.assertEqual(compare(original, current)['changed_events'][0]['fields'], ['feeling'])
        with self.Session() as db:
            self.assertEqual(db.get(Diary, self.diary_id).original_text, '测试原文')
            self.assertIn('剩余工作让我疲惫。', db.get(Diary, self.diary_id).organized.content)

    def test_review_rejects_unknown_fields_wrong_confirmation_and_concurrent_edits(self):
        from review_diary import execute, prepare
        from models.diary import Diary
        original = self.review_source(); eid = original['events'][0]['event_id']
        for changes in ({'events': [{'event_id': str(uuid4()), 'feeling': []}]},
                        {'events': [{'event_id': eid, 'body': []}]}, {'plans': '一段话'},
                        {'events': [{'event_id': eid, 'feeling': ['']}]}, {'introduction': '不在定点范围内'}):
            with self.assertRaises(ValueError): prepare(original, changes)
        packet = prepare(original, {'events': [{'event_id': eid, 'reflection': ['明确认识。']}]})
        with self.Session.begin() as db:
            with self.assertRaises(ValueError): execute(db, 'save', {'packet': packet, 'write': True, 'confirmed_sha256': 'wrong'})
        with self.Session.begin() as db:
            # 模拟直接 SQL/ORM 修改，未增加 revision 也必须检测到。
            db.get(Diary, self.diary_id).organized.events[0].body = json.dumps(['人工修订后的正文。'])
        with self.Session.begin() as db:
            with self.assertRaisesRegex(ValueError, '来源已变化'):
                execute(db, 'save', {'packet': packet, 'write': True, 'confirmed_sha256': packet['confirmation_sha256']})

    def test_review_api_roundtrip_and_source_lock(self):
        from review_diary import prepare
        from services.skill_worker import execute
        from config import settings
        from models.diary import Diary, DiaryStatus
        from services.graph_runtime import GraphError
        original = self.review_source()
        with patch('database.SessionLocal', self.Session), patch.object(settings, 'SKILL_API_USERNAME', 'isolated'):
            def call(action, params):
                return execute({'stage': 'organize-review', 'action': action, 'params': params, 'files': {}})
            current = call('export', {'diary_id': str(self.diary_id), 'user_id': str(self.user_id)})['file']
            packet = call('prepare', {'exported': current, 'changes': {'plans': ['人工明确的新计划。']}})['packet']
            self.assertFalse(call('save', {'packet': packet})['stored'])
            self.assertTrue(call('save', {'packet': packet, 'write': True, 'confirmed_sha256': packet['confirmation_sha256']})['stored'])
            with self.assertRaises(ValueError): call('export', {'diary_id': str(self.diary_id), 'user_id': str(uuid4())})
            current = call('export', {'diary_id': str(self.diary_id), 'user_id': str(self.user_id)})['file']
            packet = prepare(current, {'plans': []})
            with self.Session.begin() as db:
                db.get(Diary, self.diary_id).status = DiaryStatus.analyzed
            with self.assertRaises(GraphError):
                call('prepare', {'exported': current, 'changes': {'plans': []}})

    def test_shared_app_update_keeps_importance_edit_working(self):
        from models.diary import Diary
        from schemas.diary import DiaryOrganizedUpdate
        from services.organized_update import apply_organized_update
        self.review_source()
        with self.Session.begin() as db:
            diary = db.get(Diary, self.diary_id)
            event = diary.organized.events[0]
            old_revision = diary.organized.structured_revision
            payload = DiaryOrganizedUpdate.model_validate({'events': [{'id': str(event.id), 'user_importance': 'HIGH', 'user_importance_reason': '用户明确修订'}]})
            apply_organized_update(db, diary, payload, self.user_id)
            self.assertEqual(event.user_importance, 'HIGH')
            self.assertIsNotNone(event.importance_updated_at)
            self.assertEqual(diary.organized.structured_revision, old_revision)

    def tearDown(self):
        self.engine.dispose()

    def target(self, db):
        return load_target(db, str(self.diary_id), str(self.user_id), lock=True)

    def test_find_lists_all_matches_and_excludes_other_dates_owners_and_deleted(self):
        from datetime import datetime
        from models.user import User
        from models.diary import Diary, DiaryStatus

        second_id, other_user_id = uuid4(), uuid4()
        with self.Session.begin() as db:
            persist_result(db, self.target(db), self.result)
            db.add(User(id=other_user_id, username="other", password_encrypted="test-only"))
            db.flush()
            db.add_all([
                Diary(id=second_id, user_id=self.user_id, diary_date=date(2026, 9, 29),
                      original_text="第二条记录", status=DiaryStatus.analyzed),
                Diary(user_id=other_user_id, diary_date=date(2026, 9, 29), original_text="其他用户"),
                Diary(user_id=self.user_id, diary_date=date(2026, 9, 28), original_text="其他日期"),
                Diary(user_id=self.user_id, diary_date=date(2026, 9, 29), original_text="已删除",
                      deleted_at=datetime.utcnow()),
            ])
        with self.Session() as db:
            result = find_diaries(db, "isolated", date(2026, 9, 29))
            self.assertEqual(result["user_id"], str(self.user_id))
            self.assertEqual(result["match_count"], 2)
            matches = {row["diary_id"]: row for row in result["diaries"]}
            self.assertEqual(set(matches), {str(self.diary_id), str(second_id)})
            self.assertEqual(matches[str(self.diary_id)]["event_count"], 1)
            self.assertEqual(matches[str(self.diary_id)]["original_length"], len("测试原文"))
            self.assertEqual(matches[str(second_id)]["event_count"], 0)
            self.assertEqual(matches[str(second_id)]["status"], "analyzed")
            self.assertNotIn("original_text", matches[str(self.diary_id)])
            self.assertNotIn("selected_diary_id", result)

    def test_find_distinguishes_unknown_user_and_empty_date(self):
        with self.Session() as db:
            result = find_diaries(db, "isolated", date(2026, 10, 1))
            self.assertEqual(result["match_count"], 0)
            self.assertEqual(result["diaries"], [])
            with self.assertRaisesRegex(ValueError, "指定用户不存在"):
                find_diaries(db, "missing", date(2026, 9, 29))

    def test_find_cli_uses_default_user_without_writing(self):
        from models.user import User
        from models.diary import Diary, OrganizeTask

        with self.Session.begin() as db:
            db.get(User, self.user_id).username = "x5456"
        output = io.StringIO()
        with patch("store_diary.open_backend", return_value=self.Session), patch(
            "sys.argv", ["store_diary.py", "find", "--date", "2026-09-29"]
        ), contextlib.redirect_stdout(output):
            main()
        result = json.loads(output.getvalue())
        self.assertEqual(result["username"], "x5456")
        self.assertEqual(result["diaries"][0]["diary_id"], str(self.diary_id))
        with self.Session() as db:
            self.assertEqual(db.query(Diary).count(), 1)
            self.assertEqual(db.query(OrganizeTask).count(), 0)
            self.assertEqual(db.get(Diary, self.diary_id).original_text, "测试原文")

    def test_find_cli_rejects_invalid_date_before_database_access(self):
        with patch("store_diary.open_backend") as connect, patch(
            "sys.argv", ["store_diary.py", "find", "--date", "2026-13-01"]
        ), self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            main()
        connect.assert_not_called()

    def test_exports_analyzed_source_but_prepare_still_rejects_it(self):
        from models.diary import Diary, DiaryStatus, OrganizeTask

        with self.Session.begin() as db:
            db.get(Diary, self.diary_id).status = DiaryStatus.analyzed
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "new" / "原文.json"
            markdown, notes, packet = root / "整理稿.md", root / "澄清记录.md", root / "入库包.json"
            markdown.write_text(SAMPLE)
            notes.write_text("本次无需澄清。")
            with patch("store_diary.open_backend", return_value=self.Session):
                with patch("sys.argv", ["store_diary.py", "export", "--diary-id", str(self.diary_id),
                                       "--user-id", str(self.user_id), "--output", str(source)]), contextlib.redirect_stdout(io.StringIO()):
                    main()
                exported = json.loads(source.read_text())
                self.assertEqual(exported["original_text"], "测试原文")
                self.assertFalse(exported["capabilities"]["can_replace"])
                self.assertFalse(exported["capabilities"]["supports_event_patch"])
                with patch("sys.argv", ["store_diary.py", "prepare", "--source", str(source),
                                       "--markdown", str(markdown), "--clarifications", str(notes),
                                       "--output", str(packet)]), self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                    main()
                self.assertFalse(packet.exists())
        with self.Session() as db:
            self.assertEqual(db.get(Diary, self.diary_id).status, DiaryStatus.analyzed)
            self.assertEqual(db.query(OrganizeTask).count(), 0)

    def test_read_source_still_rejects_wrong_owner_and_deleted_diary(self):
        from datetime import datetime
        from models.diary import Diary

        with self.Session() as db, self.assertRaises(ValueError):
            load_source(db, str(self.diary_id), str(uuid4()))
        with self.Session.begin() as db:
            db.get(Diary, self.diary_id).deleted_at = datetime.utcnow()
        with self.Session() as db, self.assertRaises(ValueError):
            load_source(db, str(self.diary_id), str(self.user_id))

    def test_read_source_ignores_write_lock_but_save_target_does_not(self):
        from services.graph_runtime import GraphError

        with self.Session() as db, patch("services.graph_tasks.assert_source_writable",
                                       side_effect=GraphError("SOURCE_LOCKED", "来源锁定")):
            self.assertEqual(load_source(db, str(self.diary_id), str(self.user_id)).id, self.diary_id)
            with self.assertRaises(GraphError):
                self.target(db)

    def test_read_source_with_favorites_does_not_allow_replacement(self):
        from models.diary import DiaryEvent
        from models.favorite import Favorite

        with self.Session.begin() as db:
            persist_result(db, self.target(db), self.result)
            db.add(Favorite(user_id=self.user_id, event_id=db.query(DiaryEvent).one().id))
        with self.Session() as db:
            self.assertEqual(load_source(db, str(self.diary_id), str(self.user_id)).id, self.diary_id)
            with self.assertRaises(ValueError):
                self.target(db)

    def test_exports_only_selected_users_people(self):
        from export_people import export_people
        from models.user import User
        from models.voice_profile import PersonRelation

        with self.Session.begin() as db:
            other_id = uuid4()
            db.add(User(id=other_id, username="other", password_encrypted="test-only"))
            db.flush()
            db.add_all([
                PersonRelation(user_id=self.user_id, name="测试人物", common_names=["小名"],
                               gender="female", relation="朋友"),
                PersonRelation(user_id=other_id, name="其他用户人物", common_names=[],
                               gender="unknown", relation="朋友"),
            ])
        with self.Session() as db:
            result = export_people(db, "isolated")
            self.assertEqual(result["user_id"], str(self.user_id))
            self.assertEqual(len(result["people"]), 1)
            self.assertEqual(result["people"][0]["common_names"], ["小名"])
            self.assertEqual(result["people"][0]["gender"], "female")
            self.assertNotIn("password_encrypted", result)
            with self.assertRaises(ValueError):
                export_people(db, "missing")

    def test_create_and_replace_preserve_source_and_refresh_search(self):
        from models.diary import Diary, DiaryEvent, OrganizeTask, SearchKeywordSegment, SearchSemanticIndexState

        with self.Session.begin() as db:
            diary = self.target(db)
            initial = snapshot(diary)
            persist_result(db, diary, self.result)
        with self.Session.begin() as db:
            diary = self.target(db)
            self.assertNotEqual(initial, snapshot(diary))
            self.assertEqual(diary.original_text, "测试原文")
            self.assertEqual(diary.organized.structured_revision, 1)
            self.assertEqual(db.query(SearchSemanticIndexState).one().status, "PENDING")
            self.assertGreater(db.query(SearchKeywordSegment).count(), 0)
            changed = copy.deepcopy(self.result)
            changed["events"][0]["body"] = ["补充验证后的正文。"]
            persist_result(db, diary, changed)
        with self.Session() as db:
            diary = db.get(Diary, self.diary_id)
            self.assertEqual(diary.organized.structured_revision, 2)
            self.assertEqual(db.query(DiaryEvent).count(), 1)
            self.assertEqual(db.query(OrganizeTask).count(), 2)
            self.assertEqual(json.loads(db.query(DiaryEvent).one().body), ["补充验证后的正文。"])

    def test_write_failure_rolls_back_old_content_and_task(self):
        from models.diary import DiaryEvent, OrganizeTask

        with self.Session.begin() as db:
            persist_result(db, self.target(db), self.result)
        with self.assertRaises(RuntimeError):
            with self.Session.begin() as db:
                with patch("services.search_indexing.refresh_changed_event_search_indexes", side_effect=RuntimeError("isolated failure")):
                    persist_result(db, self.target(db), self.result)
        with self.Session() as db:
            self.assertEqual(db.query(OrganizeTask).count(), 1)
            self.assertEqual(json.loads(db.query(DiaryEvent).one().body), self.result["events"][0]["body"])

    def test_rejects_wrong_owner_and_running_task(self):
        from models.diary import OrganizeTask

        with self.Session.begin() as db:
            with self.assertRaises(ValueError):
                load_target(db, str(self.diary_id), str(uuid4()))
            persist_result(db, self.target(db), self.result)
        with self.Session.begin() as db:
            db.add(OrganizeTask(diary_id=self.diary_id, user_id=self.user_id, status="running"))
        with self.Session() as db, self.assertRaises(ValueError):
            self.target(db)

    def test_replaces_events_with_manual_importance(self):
        from models.diary import DiaryEvent

        with self.Session.begin() as db:
            persist_result(db, self.target(db), self.result)
        with self.Session.begin() as db:
            event = db.query(DiaryEvent).one()
            event.user_importance = "HIGH"
            old_id = event.id
        with self.Session.begin() as db:
            persist_result(db, self.target(db), self.result)
        with self.Session() as db:
            event = db.query(DiaryEvent).one()
            self.assertNotEqual(event.id, old_id)
            self.assertIsNone(event.user_importance)
            self.assertEqual(event.ai_importance, "MEDIUM")

    def test_rejects_event_favorites_and_detects_source_revision(self):
        from models.diary import DiaryEvent
        from models.favorite import Favorite

        with self.Session.begin() as db:
            diary = self.target(db)
            before = snapshot(diary)
            diary.original_text = "已修改原文"
            diary.content_revision += 1
            db.flush()
            self.assertNotEqual(before, snapshot(diary))
            persist_result(db, diary, self.result)
        with self.Session.begin() as db:
            db.add(Favorite(user_id=self.user_id, event_id=db.query(DiaryEvent).one().id))
        with self.Session() as db, self.assertRaises(ValueError):
            self.target(db)

    def test_cli_preview_does_not_write_and_confirmed_save_is_single_use(self):
        from models.diary import OrganizeTask

        def run(*args):
            with patch("sys.argv", ["store_diary.py", *map(str, args)]), patch(
                "store_diary.open_backend", return_value=self.Session
            ), contextlib.redirect_stdout(io.StringIO()):
                main()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            markdown, notes = root / "整理稿.md", root / "澄清记录.md"
            source, packet = root / "原文.json", root / "入库包.json"
            markdown.write_text(SAMPLE, encoding="utf-8")
            notes.write_text("本次无需澄清。", encoding="utf-8")
            run("export", "--diary-id", self.diary_id, "--user-id", self.user_id, "--output", source)
            run("prepare", "--source", source, "--markdown", markdown, "--clarifications", notes, "--output", packet)
            run("save", packet)
            with self.Session() as db:
                self.assertEqual(db.query(OrganizeTask).count(), 0)
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                run("save", packet, "--write")
            confirmed = json.loads(packet.read_text())["confirmation_sha256"]
            run("save", packet, "--write", "--confirmed-sha256", confirmed)
            with self.Session() as db:
                self.assertEqual(db.query(OrganizeTask).count(), 1)
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                run("save", packet, "--write", "--confirmed-sha256", confirmed)


if __name__ == "__main__":
    unittest.main()
