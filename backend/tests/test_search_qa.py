"""统一搜索 — 补充测试（QA 第二层验证补充覆盖）。

覆盖工程师原测试未充分覆盖的场景与边界：
- ILIKE 大小写不敏感（ASCII 关键词）。
- 分页边界：offset 超过 total 时 items 为空但 total 不变（去重口径一致）。
- 分析仅取 CURRENT 轮次：触发器不应把非 CURRENT（ARCHIVED）轮次分析内容纳入 search_text。
- search_text 中的 HTML/脚本不应回显进搜索响应（仅事件字段被序列化）。
- ILIKE 特殊字符（%、_）转义回归测试（源码已修复：% / _ 作为字面量匹配，断言仅命中字面串）。

需要启用 pg_trgm 的 PostgreSQL（与线上一致）；环境不满足时自动跳过。
"""

import json
import unittest
from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import text

from database import SessionLocal, engine
from models.diary import (
    AnalysisItem,
    AnalysisRun,
    Diary,
    DiaryEvent,
    DiaryOrganized,
    DiaryStatus,
    OrganizeTask,
)
from models.user import User
from services.search_service import search_events


def _require_pg():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT similarity('abc', 'abc')"))
    except Exception as exc:  # noqa: BLE001
        raise unittest.SkipTest(f"需要启用 pg_trgm 的 PostgreSQL：{exc}")


@unittest.skip("039 已移除 search_text 触发器；覆盖已迁至 test_diary_level_search")
class SearchQATest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _require_pg()

    def setUp(self):
        self.db = SessionLocal()
        self.user = User(username=f"search_qa_{uuid4().hex[:8]}", password_encrypted="x")
        self.db.add(self.user)
        self.db.flush()

    def tearDown(self):
        self.db.rollback()
        self.db.close()

    def _make_diary(self, status, diary_date, deleted=False):
        diary = Diary(user_id=self.user.id, original_text="原文", diary_date=diary_date, status=status)
        if deleted:
            diary.deleted_at = datetime.utcnow()
        self.db.add(diary)
        self.db.flush()
        task = OrganizeTask(diary_id=diary.id, user_id=self.user.id, status="completed", task_type="organize")
        self.db.add(task)
        self.db.flush()
        org = DiaryOrganized(
            diary_id=diary.id, task_id=task.id, title="标题", summary="", content="", mood=None, location=None,
        )
        self.db.add(org)
        self.db.flush()
        return diary, org

    def _make_event(self, org, title, body_list, search_text):
        event = DiaryEvent(
            diary_organized_id=org.id,
            event_title=title,
            body=json.dumps(body_list, ensure_ascii=False),
            feeling="[]",
            reflection="[]",
            event_tags="{}",
            search_text=search_text,
        )
        self.db.add(event)
        self.db.flush()
        self.db.execute(
            text("UPDATE diary_events SET search_text = :st WHERE id = :eid"),
            {"st": search_text, "eid": str(event.id)},
        )
        self.db.expire(event, ["search_text"])
        return event

    # ---- 1. ILIKE 大小写不敏感 ----
    def test_ilike_case_insensitive(self):
        d, o = self._make_diary(DiaryStatus.organized, date(2026, 7, 1))
        self._make_event(o, "English Mix", ["Hello World 跑步"], "Hello World 跑步")

        # 小写查询应命中含大写的文本
        items, total = search_events(self.db, self.user.id, "hello", None, None, 20, 0, mode="keyword")
        self.assertEqual(total, 1)
        # 大写查询也应命中
        items2, total2 = search_events(self.db, self.user.id, "WORLD", None, None, 20, 0, mode="keyword")
        self.assertEqual(total2, 1)

    # ---- 2. 分页边界：offset 超过 total ----
    def test_pagination_offset_beyond_total(self):
        d, o = self._make_diary(DiaryStatus.organized, date(2026, 7, 2))
        for i in range(3):
            self._make_event(o, f"关键词Z{i}", [f"包含关键词Z的第{i}条"], f"关键词Z 包含关键词Z的第{i}条")

        items, total = search_events(self.db, self.user.id, "关键词Z", None, None, 20, 100, mode="keyword")
        self.assertEqual(total, 3)          # total 不变（与 items 去重口径一致）
        self.assertEqual(items, [])         # 越界 offset 返回空

    # ---- 3. 分析仅取 CURRENT 轮次（触发器口径）----
    def test_search_text_excludes_non_current_analysis(self):
        d, o = self._make_diary(DiaryStatus.analyzed, date(2026, 7, 3))
        event = DiaryEvent(
            diary_organized_id=o.id,
            event_title="当前轮次事件",
            body=json.dumps(["事件正文内容"], ensure_ascii=False),
            feeling="[]",
            reflection="[]",
            event_tags="{}",
            search_text=None,
        )
        self.db.add(event)
        self.db.flush()

        # CURRENT 轮次分析（应包含）
        run_cur = AnalysisRun(diary_id=d.id, diary_organized_id=o.id, status="CURRENT")
        self.db.add(run_cur)
        self.db.flush()
        self.db.add(AnalysisItem(
            analysis_run_id=run_cur.id, scope="EVENT", event_id=event.id,
            analysis_type="EMOTION", content="CURRENT关键词苹果",
        ))
        self.db.flush()

        # ARCHIVED（非 CURRENT）轮次分析（应排除）
        run_old = AnalysisRun(diary_id=d.id, diary_organized_id=o.id, status="ARCHIVED")
        self.db.add(run_old)
        self.db.flush()
        self.db.add(AnalysisItem(
            analysis_run_id=run_old.id, scope="EVENT", event_id=event.id,
            analysis_type="EMOTION", content="ARCHIVED关键词香蕉",
        ))
        self.db.flush()

        # 触发器在 analysis_items 插入时已重算 search_text；再显式调用一次以保证最终态。
        self.db.execute(text("SELECT compute_event_search_vector(:eid)"), {"eid": str(event.id)})
        self.db.flush()
        self.db.refresh(event)

        self.assertIsNotNone(event.search_text)
        self.assertIn("CURRENT关键词苹果", event.search_text)
        self.assertNotIn("ARCHIVED关键词香蕉", event.search_text)

    # ---- 4. search_text 中的 HTML/脚本不应回显进响应 ----
    def test_search_text_html_not_reflected(self):
        d, o = self._make_diary(DiaryStatus.organized, date(2026, 7, 4))
        # search_text 含脚本，但响应只序列化事件字段（body），不应回显脚本。
        self._make_event(
            o, "XSS事件", ["正文内容"],
            "<script>alert(1)</script> 跑步健身",
        )

        items, total = search_events(self.db, self.user.id, "跑步健身", None, None, 20, 0, mode="keyword")
        self.assertEqual(total, 1)
        item = items[0]
        # 序列化结果仅含事件字段，不含 search_text 中的脚本。
        # default=str 处理 UUID/datetime，避免 json.dumps 报 TypeError。
        serialized = json.dumps(item, ensure_ascii=False, default=str)
        self.assertNotIn("<script>", serialized)
        self.assertNotIn("alert(1)", serialized)
        self.assertEqual(item["body"], ["正文内容"])

    # ---- 5. ILIKE 特殊字符转义回归（源码已修复：% / _ 作为字面量匹配）----
    def test_ilike_special_characters_not_treated_as_wildcards(self):
        d, o = self._make_diary(DiaryStatus.organized, date(2026, 7, 5))
        # A：含 “50” 但不含 “50%”
        a = self._make_event(o, "分数事件", ["我的分数50分 不错"], "我的分数50分 不错")
        # B：含 “50%”
        b = self._make_event(o, "比例事件", ["完成率增长50% 很好"], "完成率增长50% 很好")

        items, total = search_events(self.db, self.user.id, "50%", None, None, 20, 0, mode="keyword")
        # 正确行为：仅匹配字面 “50%”（事件 B），不应把 “50分” 当作 “50”+任意字符 命中。
        self.assertEqual(total, 1)
        self.assertEqual(items[0]["id"], b.id)
        self.assertNotIn(a.id, [it["id"] for it in items])


if __name__ == "__main__":
    unittest.main()
