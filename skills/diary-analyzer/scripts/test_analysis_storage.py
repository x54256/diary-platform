"""转换与 SQLite 隔离事务验证，不访问真实数据库。"""

import contextlib
import copy
import io
import json
import os
import re
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

from markdown_to_json import FIELDS, digest, parse_markdown, read_export, write_json
from store_analysis import (assert_current, build_export, load_target, main, make_packet,
                            open_backend, persist_result, today, validate_backend_result, verify_packet)


def event_markdown(event_id, title="同名事件", suggestion="记录一次验证结果。"):
    lines = [f"## 事件：{title}", f"事件 ID：{event_id}"]
    for label in FIELDS:
        lines.append(f"### {label}")
        if label == "可行动建议" and suggestion:
            lines.append(f"- {suggestion}")
    return "\n\n".join(lines)


def diary_markdown():
    return "## 日记级分析\n\n" + "\n\n".join(
        f"### {label}" for label in FIELDS if label != "问题解答") + "\n\n## 行动规划\n"


def action_markdown(alias="E1-S1", excerpt="记录一次验证结果。", title="记录验证结果"):
    return f"\n### 行动：{title}\n\n- 来源：{alias} | {excerpt}\n- 全天：是\n- 开始日期：{today()}\n- 重复：NONE\n"


def fixture():
    event_id = str(uuid4())
    exported = {"schema_version": 1, "source": {"diary_id": str(uuid4()), "user_id": str(uuid4())},
                "structured_diary": {"diary_date": today().isoformat(), "analysis_date": today().isoformat(),
                                     "timezone": "Asia/Shanghai", "events": [{"event_id": event_id, "title": "同名事件"}],
                                     "plans": ["明天检查参数。"]}, "person_relations": []}
    exported["export_sha256"] = digest(exported)
    return exported, event_markdown(event_id) + "\n\n" + diary_markdown() + action_markdown()


class ConversionTest(unittest.TestCase):
    def test_preserves_text_and_generates_verified_sources(self):
        exported, markdown = fixture()
        markdown = markdown.replace("### 情绪分析", "### 情绪分析\n\n- 找到 **原因** 后轻松了。\n  下一步也更清楚了。", 1)
        result = parse_markdown(markdown, exported)
        self.assertEqual(result["event_analyses"][0]["emotion_analyses"], ["找到 **原因** 后轻松了。\n下一步也更清楚了。"])
        self.assertTrue(result["action_items"][0]["source"][0]["source_key"].startswith("suggestion:event:0:"))
        self.assertEqual(result["diary_analysis"]["emotion_analyses"], [])

    def test_same_titles_and_reordered_events_bind_by_id(self):
        exported, _ = fixture()
        second_id = str(uuid4())
        exported["structured_diary"]["events"].append({"event_id": second_id, "title": "同名事件"})
        first_id = exported["structured_diary"]["events"][0]["event_id"]
        result = parse_markdown(event_markdown(second_id, suggestion="第二件事。") + "\n" +
                                event_markdown(first_id, suggestion="第一件事。") + "\n" + diary_markdown(), exported)
        self.assertEqual([e["event_id"] for e in result["event_analyses"]], [first_id, second_id])
        self.assertEqual(result["event_analyses"][0]["action_suggestions"], ["第一件事。"])

    def test_question_answers_remain_pairs(self):
        exported, markdown = fixture()
        markdown = markdown.replace("### 问题解答", "### 问题解答\n\n#### 问题：为什么？\n\n第一段。\n\n第二段。\n\n#### 问题：如何做？\n\n按条件验证。", 1)
        qa = parse_markdown(markdown, exported)["event_analyses"][0]["question_answers"]
        self.assertEqual(qa, [{"question": "为什么？", "answer": "第一段。\n\n第二段。"},
                              {"question": "如何做？", "answer": "按条件验证。"}])

    def test_rejects_lost_unknown_duplicate_or_rewritten_events(self):
        exported, markdown = fixture()
        event_id = exported["structured_diary"]["events"][0]["event_id"]
        for invalid in [markdown.replace(event_id, str(uuid4())), markdown.replace("同名事件", "改写标题"),
                        markdown.replace("### 情绪分析", "### 其他分析", 1),
                        markdown.replace("### 认知完善", "", 1),
                        event_markdown(event_id) + "\n" + markdown,
                        markdown + "\n## 其他\n不能丢弃的内容。"]:
            with self.subTest(invalid=invalid[:40]), self.assertRaises(ValueError):
                parse_markdown(invalid, exported)

    def test_rejects_invented_or_stale_action_sources(self):
        exported, markdown = fixture()
        for invalid in [markdown.replace("E1-S1 |", "E9-S1 |"),
                        markdown.replace("| 记录一次验证结果。", "| 不存在的事实。"),
                        markdown.replace("- 来源：E1-S1 | 记录一次验证结果。", ""),
                        markdown.replace("### 可行动建议\n\n- 记录一次验证结果。", "### 可行动建议")]:
            with self.assertRaises(ValueError):
                parse_markdown(invalid, exported)
        sources = parse_markdown(markdown.replace("E1-S1", "错误别名"), exported, sources_only=True)
        self.assertEqual({x["alias"] for x in sources}, {"P1", "E1-S1"})

    def test_rejects_invalid_schedules_and_accepts_timed_recurring_actions(self):
        exported, markdown = fixture()
        for value in ["WEEKLY", "MONTHLY_DATE", "MONTHLY_NTH_WEEKDAY", "YEARLY", "UNKNOWN"]:
            with self.assertRaises(ValueError):
                parse_markdown(markdown.replace("重复：NONE", f"重复：{value}"), exported)
        for invalid in [markdown.replace("全天：是", "全天：否"),
                        markdown.replace(str(today()), "2001-01-01"),
                        markdown + "- 次数：2\n", markdown + "- 月份：4\n",
                        markdown + "- 开始日期：2026-01-01\n"]:
            with self.assertRaises(ValueError):
                parse_markdown(invalid, exported)
        recurring = markdown.replace("全天：是", "全天：否\n- 开始时间：09:00\n- 结束时间：10:00")
        recurring = recurring.replace("重复：NONE", "重复：WEEKLY\n- 星期：1,3\n- 间隔：2")
        result = parse_markdown(recurring, exported)
        self.assertEqual(result["action_items"][0]["schedule"]["start_time"], "09:00:00")

    def test_packet_binds_markdown_source_and_result(self):
        exported, markdown = fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            draft, source = root / "分析稿.md", root / "来源.json"
            draft.write_text(markdown)
            write_json(source, exported)
            packet = make_packet(draft, source)
            self.assertEqual(verify_packet(packet), packet["result"])
            for changed in ["result", "markdown"]:
                tampered = copy.deepcopy(packet)
                tampered[changed] = {}
                with self.assertRaises(ValueError):
                    verify_packet(tampered)
            with self.assertRaises(ValueError):
                verify_packet(packet, "wrong")
            draft.write_text(markdown + "\n")
            with self.assertRaises(ValueError):
                verify_packet(packet)
            draft.write_text(markdown)
            source.write_text(source.read_text().replace("明天检查参数。", "篡改计划。"))
            with self.assertRaises(ValueError):
                read_export(source)
            with self.assertRaises(ValueError):
                verify_packet(packet)

    def test_documented_example_converts(self):
        root = Path(__file__).resolve().parents[1]
        example = re.search(r"```markdown\n(.*?)\n```", (root / "references/markdown-format.md").read_text(), re.S)[1]
        exported, _ = fixture()
        exported["structured_diary"]["analysis_date"] = "2026-10-27"
        exported["structured_diary"]["events"] = [{"event_id": "11111111-1111-4111-8111-111111111111", "title": "验证脚本参数"}]
        self.assertEqual(len(parse_markdown(example, exported)["action_items"]), 1)


class StorageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cwd = Path.cwd()
        try:
            open_backend(Path(__file__).resolve().parents[3] / "backend")
        finally:
            os.chdir(cwd)
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

        cls.metadata = MetaData()
        for table in Base.metadata.tables.values():
            clone = table.to_metadata(cls.metadata)
            clone.indexes.clear()
            if clone.name.startswith("graph_"):
                for constraint in list(clone.constraints):
                    if isinstance(constraint, CheckConstraint):
                        clone.constraints.remove(constraint)
            for column in clone.columns:
                default = getattr(column.server_default, "arg", None)
                if default is not None and "gen_random_uuid()" in str(default):
                    column.server_default = None
                elif default is not None and "::jsonb" in str(default):
                    column.server_default = DefaultClause(text(str(default).replace("::jsonb", "")))

    def setUp(self):
        from sqlalchemy import create_engine, event
        from sqlalchemy.orm import sessionmaker
        from models.user import User
        from models.diary import Diary, DiaryOrganized, DiaryEvent, DiaryStatus, OrganizeTask
        self.engine = create_engine("sqlite://")

        @event.listens_for(self.engine, "connect")
        def sqlite_functions(connection, record):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.create_function("LEAST", 2, min, deterministic=True)
            connection.create_function("GREATEST", 2, max, deterministic=True)
            connection.create_function("BTRIM", 1, lambda x: x.strip() if x else x, deterministic=True)
            connection.create_function("jsonb_typeof", 1, lambda x: "object" if isinstance(json.loads(x), dict) else "array", deterministic=True)

        self.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.user_id, self.diary_id = uuid4(), uuid4()
        self.event_ids = [uuid4(), uuid4()]
        with self.Session.begin() as db:
            db.add(User(id=self.user_id, username="isolated", password_encrypted="test-only"))
            db.flush()
            diary = Diary(id=self.diary_id, user_id=self.user_id, diary_date=today(), original_text="测试来源", status=DiaryStatus.organized)
            db.add(diary)
            db.flush()
            task = OrganizeTask(diary_id=diary.id, user_id=self.user_id, task_type="organize", status="completed")
            db.add(task)
            db.flush()
            organized = DiaryOrganized(diary_id=diary.id, task_id=task.id, source_content_revision=1,
                                      structured_revision=1, title="原总标题", summary="原摘要", location="原地点", mood="平静",
                                      introduction="背景", trivia="[]", plans=json.dumps(["明天检查参数。"], ensure_ascii=False))
            db.add(organized)
            db.flush()
            # 同名、同 sort_order 事件也必须按 ID 定位。
            for event_id in self.event_ids:
                db.add(DiaryEvent(id=event_id, diary_organized_id=organized.id, event_title="同名事件",
                                  body=json.dumps(["完成验证。"]), feeling="[]", reflection="[]",
                                  event_tags='{"topic":["验证"]}', sort_order=0, ai_importance="LOW"))
        with self.Session() as db:
            self.exported = build_export(db, self.target(db))
        self.ordered_ids = [x["event_id"] for x in self.exported["structured_diary"]["events"]]
        self.markdown = "\n\n".join(event_markdown(x) for x in reversed(self.ordered_ids)) + "\n" + diary_markdown() + action_markdown()
        self.result = parse_markdown(self.markdown, self.exported)

    def test_api_analysis_saves_uploaded_draft_and_rejects_stale_confirmation(self):
        from config import settings
        from services.skill_worker import execute
        from models.diary import AnalysisRun, Diary
        md, source = '/cloud/analysis/分析稿.md', '/cloud/analysis/source.json'
        with patch('database.SessionLocal', self.Session), patch.object(settings, 'SKILL_API_USERNAME', 'isolated'):
            def call(action, params, files=None):
                return execute({'stage': 'analyze', 'action': action, 'params': params, 'files': files or {}})
            exported = call('export', {'diary_id': str(self.diary_id), 'user_id': str(self.user_id)})['file']
            files = {md: self.markdown, source: json.dumps(exported, ensure_ascii=False)}
            packet = call('prepare', {'markdown': md, 'source': source}, files)['packet']
            with self.Session() as db: self.assertEqual(db.query(AnalysisRun).count(), 0)
            with self.assertRaises(ValueError):
                call('save', {'packet': packet, 'write': True, 'confirmed_sha256': 'wrong'}, files)
            with self.assertRaises(ValueError):
                call('save', {'packet': packet, 'write': True, 'confirmed_sha256': packet['confirmation_sha256']}, {**files, md: self.markdown + '\n改稿'})
            receipt = call('save', {'packet': packet, 'write': True, 'confirmed_sha256': packet['confirmation_sha256']}, files)
            self.assertEqual(receipt['actions'], 1)
            with self.Session() as db:
                self.assertEqual(db.get(Diary, self.diary_id).status.value, 'analyzed')
                self.assertEqual(db.query(AnalysisRun).count(), 1)

    def tearDown(self):
        self.engine.dispose()

    def target(self, db, lock=False):
        return load_target(db, str(self.diary_id), str(self.user_id), lock=lock)

    def test_save_binds_exact_event_and_preserves_metadata_and_graph(self):
        from models.diary import AnalysisRun, AnalysisItem, Diary, DiaryActionItem, DiaryActionEventLink, SearchKeywordSegment
        from models.graph import GraphTask, GraphRun
        with self.Session.begin() as db:
            before = build_export(db, self.target(db))
            validate_backend_result(self.result)
            receipt = persist_result(db, self.target(db, lock=True), self.result)
            self.assertEqual(receipt["actions"], 1)
        with self.Session() as db:
            diary = db.get(Diary, self.diary_id)
            self.assertEqual(diary.status.value, "analyzed")
            self.assertEqual((diary.organized.title, diary.organized.summary, diary.organized.location, diary.organized.mood),
                             ("原总标题", "原摘要", "原地点", "平静"))
            self.assertEqual(diary.original_text, "测试来源")
            self.assertEqual(build_export(db, diary)["structured_diary"], before["structured_diary"])
            self.assertTrue(all(e.event_tags == '{"topic":["验证"]}' for e in diary.organized.events))
            self.assertEqual(db.query(AnalysisRun).one().mood, "平静")
            self.assertEqual(db.query(AnalysisItem).count(), 2)
            self.assertEqual(db.query(DiaryActionEventLink).one().diary_event_id, UUID(self.ordered_ids[0]))
            self.assertEqual(db.query(DiaryActionItem).one().source_kind, "SUGGESTION")
            self.assertGreater(db.query(SearchKeywordSegment).count(), 0)
            self.assertEqual(db.query(GraphTask).count(), 0)
            self.assertEqual(db.query(GraphRun).count(), 0)
            with self.assertRaises(ValueError):
                self.target(db)

    def test_rollback_keeps_diary_unanalyzed_and_creates_nothing(self):
        from models.diary import AnalysisRun, DiaryActionItem, Diary, OrganizeTask
        with self.assertRaises(RuntimeError):
            with self.Session.begin() as db, patch("services.search_indexing.refresh_changed_event_search_indexes",
                                                 side_effect=RuntimeError("isolated")):
                persist_result(db, self.target(db), self.result)
        with self.Session() as db:
            self.assertEqual(db.get(Diary, self.diary_id).status.value, "organized")
            self.assertEqual(db.query(AnalysisRun).count(), 0)
            self.assertEqual(db.query(DiaryActionItem).count(), 0)
            self.assertEqual(db.query(OrganizeTask).count(), 1)

    def test_rejects_historical_analysis_dirty_deleted_wrong_owner_and_running_task(self):
        from models.diary import AnalysisRun, Diary, OrganizeTask
        from datetime import datetime
        with self.Session() as db, self.assertRaises(ValueError):
            load_target(db, str(self.diary_id), str(uuid4()))
        for field, value in [("is_dirty", True), ("deleted_at", datetime.utcnow()), ("content_revision", 2)]:
            with self.Session() as db:
                setattr(db.get(Diary, self.diary_id), field, value)
                db.flush()
                with self.assertRaises(ValueError):
                    self.target(db)
                db.rollback()
        with self.Session() as db:
            db.add(AnalysisRun(diary_id=self.diary_id, diary_organized_id=self.target(db).organized.id, status="ARCHIVED"))
            db.flush()
            with self.assertRaises(ValueError):
                self.target(db)
            db.rollback()
        with self.Session() as db:
            db.add(OrganizeTask(diary_id=self.diary_id, user_id=self.user_id, status="running"))
            db.flush()
            with self.assertRaises(ValueError):
                self.target(db)

    def test_source_and_people_changes_stop_prepared_save(self):
        from models.diary import DiaryEvent
        from models.voice_profile import PersonRelation
        with self.Session() as db:
            diary = self.target(db)
            assert_current(db, diary, self.exported)
            db.get(DiaryEvent, self.event_ids[0]).body = json.dumps(["来源已变化。"])
            db.flush()
            with self.assertRaises(ValueError):
                assert_current(db, diary, self.exported)
            db.rollback()
        with self.Session() as db:
            db.add(PersonRelation(user_id=self.user_id, name="人物", common_names=[], gender="unknown", relation="朋友"))
            db.flush()
            with self.assertRaises(ValueError):
                assert_current(db, self.target(db), self.exported)

    def test_backend_accepts_timed_recurring_schedule_and_rejects_stale_dates(self):
        recurring = self.markdown.replace("全天：是", "全天：否\n- 开始时间：09:00\n- 结束时间：10:00")
        recurring = recurring.replace("重复：NONE", "重复：WEEKLY\n- 星期：1,3")
        result = parse_markdown(recurring, self.exported)
        with self.Session.begin() as db:
            validate_backend_result(result)
            persist_result(db, self.target(db), result)
        from store_analysis import assert_fresh_dates
        result["action_items"][0]["schedule"]["start_date"] = "2001-01-01"
        with self.assertRaises(ValueError):
            assert_fresh_dates(result)

    def test_user_graph_task_blocks_import(self):
        from models.graph import GraphTask
        with self.Session() as db:
            db.add(GraphTask(user_id=self.user_id, entry_type="HISTORY", date_from=today(), date_to=today(),
                             status="RUNNING", config_snapshot={}))
            db.flush()
            with self.assertRaises(ValueError):
                self.target(db)

    def test_emotion_only_still_refreshes_keywords(self):
        from models.diary import SearchKeywordSegment
        no_actions = "\n".join(event_markdown(x, suggestion="") for x in self.ordered_ids) + "\n" + diary_markdown()
        no_actions = no_actions.replace("### 情绪分析", "### 情绪分析\n\n- 验证结果让你放松。", 1)
        result = parse_markdown(no_actions, self.exported)
        with self.Session.begin() as db:
            persist_result(db, self.target(db), result)
        with self.Session() as db:
            rows = db.query(SearchKeywordSegment).filter(SearchKeywordSegment.kind == "analysis_emotion").all()
            self.assertEqual([r.content for r in rows], ["验证结果让你放松。"])

    def test_cli_readonly_then_confirmed_single_use_save(self):
        from models.diary import AnalysisRun
        def run(*args):
            with patch("sys.argv", ["store_analysis.py", *map(str, args)]), patch(
                "store_analysis.open_backend", return_value=self.Session
            ), contextlib.redirect_stdout(io.StringIO()):
                main()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, draft, packet = root / "来源.json", root / "分析稿.md", root / "入库包.json"
            draft.write_text(self.markdown)
            run("export", "--diary-id", self.diary_id, "--user-id", self.user_id, "--output", source)
            run("prepare", "--source", source, "--markdown", draft, "--output", packet)
            run("save", packet)
            with self.Session() as db:
                self.assertEqual(db.query(AnalysisRun).count(), 0)
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                run("save", packet, "--write")
            confirmed = json.loads(packet.read_text())["confirmation_sha256"]
            run("save", packet, "--write", "--confirmed-sha256", confirmed)
            with self.Session() as db:
                self.assertEqual(db.query(AnalysisRun).count(), 1)
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                run("save", packet, "--write", "--confirmed-sha256", confirmed)


if __name__ == "__main__":
    unittest.main()
