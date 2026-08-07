"""统一搜索接口测试（鉴权 / 校验 / 状态覆盖 / 软删除 / 日期范围 / 分页 / 相关度顺序）。

测试策略：
- 使用最小测试应用复用生产 diaries 路由，并挂载到与生产一致的前缀 /diary，
  避免触发主应用 startup（调度器 / 建表）副作用。
- 通过事务内会话（connection + transaction）覆盖 get_db 依赖，使未提交的测试用例
  数据对端点可见；用例结束后整体回滚，互不污染。
- 以原生 SQL 直接固定 diary_events.search_text，与触发器实现解耦，保证断言可复现。

需要启用 pg_trgm 的 PostgreSQL（与线上一致）；search_text 列需已由迁移 036 建立。
环境不满足时自动跳过。
"""

import json
import unittest
from datetime import date, datetime
from uuid import uuid4

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from database import SessionLocal, engine, get_db
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
from routers.diaries import router as diaries_router
from services.auth import create_access_token, get_current_user


SEARCH_PATH = "/diary/api/diaries/search"


def _require_pg():
    """跳过无 PG / 未启用 pg_trgm 的环境。"""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT similarity('abc', 'abc')"))
    except Exception as exc:  # noqa: BLE001
        raise unittest.SkipTest(f"需要启用 pg_trgm 的 PostgreSQL：{exc}")


# 最小测试应用：复用生产 diaries 路由并挂载到 /diary 前缀，仅覆盖 get_db。
_test_app = FastAPI()
_sub = APIRouter(prefix="/diary")
_sub.include_router(diaries_router)
_test_app.include_router(_sub)


@unittest.skip("039 已替换事件级 search_text API；覆盖已迁至日记级搜索测试")
class SearchAPITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _require_pg()

    def setUp(self):
        # 单一连接 + 显式事务，使未提交的测试数据对端点可见，用例结束后整体回滚。
        self.connection = engine.connect()
        self.transaction = self.connection.begin()
        self.session = SessionLocal(bind=self.connection)

        def override_get_db():
            try:
                yield self.session
            finally:
                pass

        _test_app.dependency_overrides[get_db] = override_get_db
        # raise_server_exceptions=False：让校验失败（如 422）以状态码形式返回，便于断言；
        # 否则 FastAPI 的 ValidationError 会被 TestClient 直接抛成异常。
        self.client = TestClient(_test_app, raise_server_exceptions=False)

        # 创建测试用户并签发 JWT（与 get_current_user 使用同一 SECRET_KEY）。
        self.user = User(username=f"search_api_{uuid4().hex[:8]}", password_encrypted="x")
        self.session.add(self.user)
        self.session.flush()
        self.token = create_access_token({"sub": self.user.username})
        self.auth_headers = {"Authorization": f"Bearer {self.token}"}

    def tearDown(self):
        _test_app.dependency_overrides.clear()
        self.session.close()
        self.transaction.rollback()
        self.connection.close()

    # ---- 数据构造辅助 ----
    def _make_diary(self, status, diary_date, deleted=False):
        diary = Diary(user_id=self.user.id, original_text="原文", diary_date=diary_date, status=status)
        if deleted:
            diary.deleted_at = datetime.utcnow()
        self.session.add(diary)
        self.session.flush()
        task = OrganizeTask(diary_id=diary.id, user_id=self.user.id, status="completed", task_type="organize")
        self.session.add(task)
        self.session.flush()
        org = DiaryOrganized(
            diary_id=diary.id, task_id=task.id, title="标题", summary="", content="", mood=None, location=None,
        )
        self.session.add(org)
        self.session.flush()
        return diary, org

    def _make_diary_for_user(self, user, status, diary_date):
        diary = Diary(user_id=user.id, original_text="原文", diary_date=diary_date, status=status)
        self.session.add(diary)
        self.session.flush()
        task = OrganizeTask(diary_id=diary.id, user_id=user.id, status="completed", task_type="organize")
        self.session.add(task)
        self.session.flush()
        org = DiaryOrganized(
            diary_id=diary.id, task_id=task.id, title="标题", summary="", content="", mood=None, location=None,
        )
        self.session.add(org)
        self.session.flush()
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
        self.session.add(event)
        self.session.flush()
        # 以原生 SQL 直接固定 search_text，绕过触发器对事件字段的自动重算，
        # 使断言（ILIKE 命中 / similarity 排序）与触发器实现解耦、确定可复现。
        self.session.execute(
            text("UPDATE diary_events SET search_text = :st WHERE id = :eid"),
            {"st": search_text, "eid": str(event.id)},
        )
        self.session.expire(event, ["search_text"])
        return event

    def _make_analysis(self, diary, event, content):
        run = AnalysisRun(diary_id=diary.id, diary_organized_id=event.diary_organized_id, status="CURRENT")
        self.session.add(run)
        self.session.flush()
        item = AnalysisItem(
            analysis_run_id=run.id, scope="EVENT", event_id=event.id,
            analysis_type="EMOTION", content=content,
        )
        self.session.add(item)
        self.session.flush()
        return run, item

    def _event_id_for(self, org):
        return self.session.query(DiaryEvent).filter(DiaryEvent.diary_organized_id == org.id).first().id

    # ---- 测试用例 ----
    def test_unauthenticated_returns_401(self):
        resp = self.client.get(SEARCH_PATH, params={"q": "任意"})
        self.assertEqual(resp.status_code, 401)

    def test_empty_query_returns_422(self):
        resp = self.client.get(SEARCH_PATH, params={"q": ""}, headers=self.auth_headers)
        self.assertEqual(resp.status_code, 422)

    def test_status_coverage_organized_and_analyzed(self):
        d_org, o_org = self._make_diary(DiaryStatus.organized, date(2026, 2, 1))
        d_anl, o_anl = self._make_diary(DiaryStatus.analyzed, date(2026, 2, 2))
        d_saved, o_saved = self._make_diary(DiaryStatus.saved, date(2026, 2, 3))
        self._make_event(o_org, "关键词A事件", ["包含关键词A"], "关键词A 包含关键词A")
        self._make_event(o_anl, "关键词A事件2", ["包含关键词A"], "关键词A 包含关键词A")
        self._make_event(o_saved, "关键词A事件3", ["包含关键词A"], "关键词A 包含关键词A")

        resp = self.client.get(
            SEARCH_PATH, params={"q": "关键词A"}, headers=self.auth_headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total"], 2)
        returned_ids = {it["id"] for it in data["items"]}
        self.assertNotIn(str(self._event_id_for(o_saved)), returned_ids)

    def test_soft_deleted_excluded(self):
        d_del, o_del = self._make_diary(DiaryStatus.organized, date(2026, 3, 1), deleted=True)
        self._make_event(o_del, "关键词B", ["包含关键词B"], "关键词B 包含关键词B")

        resp = self.client.get(
            SEARCH_PATH, params={"q": "关键词B"}, headers=self.auth_headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total"], 0)
        self.assertEqual(data["items"], [])

    def test_date_range_filter(self):
        d_early, o_early = self._make_diary(DiaryStatus.organized, date(2026, 1, 10))
        d_late, o_late = self._make_diary(DiaryStatus.organized, date(2026, 3, 10))
        self._make_event(o_early, "关键词C", ["包含关键词C"], "关键词C 包含关键词C")
        self._make_event(o_late, "关键词C", ["包含关键词C"], "关键词C 包含关键词C")

        resp = self.client.get(
            SEARCH_PATH,
            params={"q": "关键词C", "start_date": "2026-03-01", "end_date": "2026-03-31"},
            headers=self.auth_headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["diary_date"], "2026-03-10")

    def test_pagination_and_precise_total(self):
        d, o = self._make_diary(DiaryStatus.organized, date(2026, 5, 1))
        for i in range(3):
            self._make_event(o, f"关键词E{i}", [f"包含关键词E的第{i}条"], f"关键词E 包含关键词E的第{i}条")

        resp1 = self.client.get(
            SEARCH_PATH, params={"q": "关键词E", "limit": 2, "offset": 0}, headers=self.auth_headers,
        )
        self.assertEqual(resp1.status_code, 200)
        data1 = resp1.json()
        self.assertEqual(data1["total"], 3)
        self.assertEqual(len(data1["items"]), 2)

        resp2 = self.client.get(
            SEARCH_PATH, params={"q": "关键词E", "limit": 2, "offset": 2}, headers=self.auth_headers,
        )
        data2 = resp2.json()
        self.assertEqual(len(data2["items"]), 1)

    def test_relevance_order_title_exact_first(self):
        d1, o1 = self._make_diary(DiaryStatus.organized, date(2026, 1, 1))
        d2, o2 = self._make_diary(DiaryStatus.organized, date(2026, 1, 2))
        e1 = self._make_event(o1, "跑步健身日记", ["今天去跑步了"], "跑步健身 今天去跑步了")
        # e2 的 search_text 必须包含查询子串“跑步健身”，否则 ILIKE 仅命中 1 条。
        e2 = self._make_event(o2, "读书笔记", ["今天去跑步健身顺便买了书"], "读书笔记 今天去跑步健身顺便买了书")

        resp = self.client.get(
            SEARCH_PATH, params={"q": "跑步健身"}, headers=self.auth_headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["items"][0]["id"], str(e1.id))
        self.assertEqual(data["items"][1]["id"], str(e2.id))
        # 相关度分应随排序递减
        self.assertGreaterEqual(data["items"][0]["rank"], data["items"][1]["rank"])

    def test_response_shape_has_extra_fields(self):
        d, o = self._make_diary(DiaryStatus.organized, date(2026, 4, 1))
        e = self._make_event(o, "关键词D", ["正文包含关键词D"], "关键词D 正文包含关键词D")
        self._make_analysis(d, e, "分析也提到关键词D")

        resp = self.client.get(
            SEARCH_PATH, params={"q": "关键词D"}, headers=self.auth_headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total"], 1)
        item = data["items"][0]
        # 检索附加字段齐备
        self.assertEqual(item["id"], str(e.id))
        self.assertIn("diary_id", item)
        self.assertIn("diary_date", item)
        self.assertIn("rank", item)
        self.assertIn("analysis_run_id", item)
        # 关联分析被组装进响应
        self.assertTrue(len(item["analysis"]) >= 1)

    def test_default_mode_is_hybrid_and_matched_chunk_types_present(self):
        d, o = self._make_diary(DiaryStatus.organized, date(2026, 4, 1))
        e = self._make_event(o, "关键词D", ["正文包含关键词D"], "关键词D 正文包含关键词D")
        self._make_analysis(d, e, "分析也提到关键词D")

        # 不传 mode，默认应为 hybrid（决策 9）。
        resp = self.client.get(
            SEARCH_PATH, params={"q": "关键词D"}, headers=self.auth_headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total"], 1)
        item = data["items"][0]
        # 命中语义层字段存在且为列表（语义分支不可用时为空列表，fail-open）。
        self.assertIn("matched_chunk_types", item)
        self.assertIsInstance(item["matched_chunk_types"], list)
        # 关键词命中仍能召回（语义不可用时降级关键词）。
        self.assertEqual(len(item["analysis"]) >= 1, True)


@unittest.skip("039 固定混合搜索，不再提供 mode 参数")
class SearchAPIModeValidationTest(unittest.TestCase):
    """模式参数校验：需 PG（鉴权需查 users 表），但不需要 pgvector / event_embedding_chunks。

    mode 经 SearchMode Literal 在参数校验阶段即完成白名单校验，非法值直接 422，
    早于检索逻辑；合法 mode 通过 schema（检索是否成功取决于索引/配置，本测试仅
    断言非 422）。
    """

    @classmethod
    def setUpClass(cls):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001
            raise unittest.SkipTest(f"需要可用的 PostgreSQL（鉴权用）：{exc}")

    def setUp(self):
        self.connection = engine.connect()
        self.transaction = self.connection.begin()
        self.session = SessionLocal(bind=self.connection)

        def override_get_db():
            try:
                yield self.session
            finally:
                pass

        self.app = FastAPI()
        sub = APIRouter(prefix="/diary")
        sub.include_router(diaries_router)
        self.app.include_router(sub)
        self.app.dependency_overrides[get_db] = override_get_db
        # raise_server_exceptions=False：让校验失败（如 422）以状态码形式返回。
        self.client = TestClient(self.app, raise_server_exceptions=False)

        # 真实用户（写入当前事务，对端点可见）。
        self.user = User(username=f"mode_valid_{uuid4().hex[:8]}", password_encrypted="x")
        self.session.add(self.user)
        self.session.flush()
        self.token = create_access_token({"sub": self.user.username})
        self.auth_headers = {"Authorization": f"Bearer {self.token}"}

        # FastAPI 实际会先执行 security 依赖（get_current_user）再校验 query 参数；
        # 为避免鉴权（或 DB 可用性）干扰对 mode 白名单校验本身的断言，覆盖鉴权依赖。
        def _override_current_user():
            return self.user

        self.app.dependency_overrides[get_current_user] = _override_current_user

    def tearDown(self):
        self.app.dependency_overrides.clear()
        self.session.close()
        self.transaction.rollback()
        self.connection.close()

    def test_invalid_mode_returns_422(self):
        resp = self.client.get(
            SEARCH_PATH, params={"q": "任意", "mode": "bogus"}, headers=self.auth_headers,
        )
        self.assertEqual(resp.status_code, 422)

    def test_valid_modes_accepted_by_schema(self):
        # 合法 mode 通过 schema 校验（不触发 422；检索成败取决于索引/配置，仅断言非 422）。
        for mode in ("keyword", "semantic", "hybrid"):
            resp = self.client.get(
                SEARCH_PATH, params={"q": "任意", "mode": mode}, headers=self.auth_headers,
            )
            self.assertNotEqual(resp.status_code, 422)


if __name__ == "__main__":
    unittest.main()
