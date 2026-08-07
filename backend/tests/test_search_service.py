"""统一搜索服务层测试：排序 / 过滤 / 去重 / 精确计数。

说明：本测试通过手动设置 diary_events.search_text 来隔离触发器逻辑，
专注验证 search_service 的跨表过滤、similarity 排序、按事件去重与精确 total。
需要启用 pg_trgm 的 PostgreSQL（与线上一致）；环境不满足时自动跳过。

隔离策略：每个用例在独立事务中插入数据，tearDown 回滚，互不污染。
"""

import json
import unittest
from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import text
from unittest.mock import patch

from database import SessionLocal, engine
from models.diary import (
    AnalysisItem,
    AnalysisRun,
    Diary,
    DiaryEvent,
    DiaryOrganized,
    DiaryStatus,
    EventEmbeddingChunk,
    OrganizeTask,
)
from models.user import User
from services.search_service import _escape_like, _rrf_fuse, search_events


def _require_pg():
    """跳过无 PG / 未启用 pg_trgm 的环境。"""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT similarity('abc', 'abc')"))
    except Exception as exc:  # noqa: BLE001
        raise unittest.SkipTest(f"需要启用 pg_trgm 的 PostgreSQL：{exc}")


def _require_vector():
    """跳过未安装 pgvector / 未建 event_embedding_chunks 表的环境（语义分支依赖）。

    关键词分支（pg_trgm）不依赖此表；仅语义召回需要，故单独成检查。
    """
    try:
        with engine.connect() as conn:
            exists = conn.execute(
                text("SELECT to_regclass('public.event_embedding_chunks')")
            ).scalar()
            if exists is None:
                raise unittest.SkipTest(
                    "需要 event_embedding_chunks 表（pgvector 未安装，跳过语义召回测试）"
                )
    except unittest.SkipTest:
        raise
    except Exception as exc:  # noqa: BLE001
        raise unittest.SkipTest(f"需要启用 pgvector 的 PostgreSQL：{exc}")


@unittest.skip("039 已移除 search_text 事件级搜索；覆盖已迁至 test_diary_level_search")
class SearchServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _require_pg()

    def setUp(self):
        self.db = SessionLocal()
        self.user = User(username=f"search_svc_{uuid4().hex[:8]}", password_encrypted="x")
        self.db.add(self.user)
        self.db.flush()

    def tearDown(self):
        self.db.rollback()
        self.db.close()

    # ---- 数据构造辅助 ----
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

    def _make_diary_for_user(self, user, status, diary_date):
        diary = Diary(user_id=user.id, original_text="原文", diary_date=diary_date, status=status)
        self.db.add(diary)
        self.db.flush()
        task = OrganizeTask(diary_id=diary.id, user_id=user.id, status="completed", task_type="organize")
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
        # 以原生 SQL 直接固定 search_text，绕过触发器对事件字段的自动重算，
        # 使断言（ILIKE 命中 / similarity 排序）与触发器实现解耦、确定可复现。
        self.db.execute(
            text("UPDATE diary_events SET search_text = :st WHERE id = :eid"),
            {"st": search_text, "eid": str(event.id)},
        )
        self.db.expire(event, ["search_text"])
        return event

    def _make_analysis(self, diary, event, content):
        run = AnalysisRun(diary_id=diary.id, diary_organized_id=event.diary_organized_id, status="CURRENT")
        self.db.add(run)
        self.db.flush()
        item = AnalysisItem(
            analysis_run_id=run.id, scope="EVENT", event_id=event.id,
            analysis_type="EMOTION", content=content,
        )
        self.db.add(item)
        self.db.flush()
        return run, item

    def _event_id_for(self, org):
        return self.db.query(DiaryEvent).filter(DiaryEvent.diary_organized_id == org.id).first().id

    # ---- 测试用例 ----
    def test_ranking_by_similarity_title_exact_first(self):
        d1, o1 = self._make_diary(DiaryStatus.organized, date(2026, 1, 1))
        d2, o2 = self._make_diary(DiaryStatus.organized, date(2026, 1, 2))
        e1 = self._make_event(o1, "跑步健身日记", ["今天去跑步了"], "跑步健身 今天去跑步了")
        # 注意：e2 的 search_text 必须包含查询子串“跑步健身”，否则 ILIKE 不会命中，
        # 之前写成“今天去跑步了”缺“健身”会导致仅命中 1 条，断言 total==2 失败。
        e2 = self._make_event(o2, "读书笔记", ["今天去跑步健身顺便买了书"], "读书笔记 今天去跑步健身顺便买了书")

        items, total = search_events(self.db, self.user.id, "跑步健身", None, None, 20, 0, mode="keyword")
        self.assertEqual(total, 2)
        # 标题精确包含关键词，相关度应高于仅正文命中的事件
        self.assertEqual(items[0]["id"], e1.id)
        self.assertEqual(items[1]["id"], e2.id)

    def test_status_filter_includes_organized_and_analyzed(self):
        d_org, o_org = self._make_diary(DiaryStatus.organized, date(2026, 2, 1))
        d_anl, o_anl = self._make_diary(DiaryStatus.analyzed, date(2026, 2, 2))
        d_saved, o_saved = self._make_diary(DiaryStatus.saved, date(2026, 2, 3))
        self._make_event(o_org, "关键词A事件", ["包含关键词A"], "关键词A 包含关键词A")
        self._make_event(o_anl, "关键词A事件2", ["包含关键词A"], "关键词A 包含关键词A")
        self._make_event(o_saved, "关键词A事件3", ["包含关键词A"], "关键词A 包含关键词A")

        items, total = search_events(self.db, self.user.id, "关键词A", None, None, 20, 0, mode="keyword")
        self.assertEqual(total, 2)
        returned_ids = {it["id"] for it in items}
        self.assertNotIn(self._event_id_for(o_saved), returned_ids)

    def test_soft_deleted_excluded(self):
        d_del, o_del = self._make_diary(DiaryStatus.organized, date(2026, 3, 1), deleted=True)
        self._make_event(o_del, "关键词B", ["包含关键词B"], "关键词B 包含关键词B")

        items, total = search_events(self.db, self.user.id, "关键词B", None, None, 20, 0, mode="keyword")
        self.assertEqual(total, 0)
        self.assertEqual(items, [])

    def test_date_range_filter(self):
        d_early, o_early = self._make_diary(DiaryStatus.organized, date(2026, 1, 10))
        d_late, o_late = self._make_diary(DiaryStatus.organized, date(2026, 3, 10))
        self._make_event(o_early, "关键词C", ["包含关键词C"], "关键词C 包含关键词C")
        self._make_event(o_late, "关键词C", ["包含关键词C"], "关键词C 包含关键词C")

        items, total = search_events(self.db, self.user.id, "关键词C", date(2026, 3, 1), date(2026, 3, 31), 20, 0, mode="keyword")
        self.assertEqual(total, 1)
        self.assertEqual(items[0]["diary_date"], date(2026, 3, 10))

    def test_dedup_single_event_with_body_and_analysis(self):
        d, o = self._make_diary(DiaryStatus.organized, date(2026, 4, 1))
        e = self._make_event(o, "关键词D", ["正文包含关键词D"], "关键词D 正文包含关键词D")
        self._make_analysis(d, e, "分析也提到关键词D")
        # 触发器可能已重算 search_text；固定为包含关键词D的值，确保命中且只计一次
        e.search_text = "关键词D 正文包含关键词D 分析也提到关键词D"
        self.db.flush()

        items, total = search_events(self.db, self.user.id, "关键词D", None, None, 20, 0, mode="keyword")
        self.assertEqual(total, 1)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], e.id)
        # 关联分析应被组装进响应
        self.assertTrue(len(items[0]["analysis"]) >= 1)

    def test_precise_total_with_pagination(self):
        d, o = self._make_diary(DiaryStatus.organized, date(2026, 5, 1))
        for i in range(3):
            self._make_event(o, f"关键词E{i}", [f"包含关键词E的第{i}条"], f"关键词E 包含关键词E的第{i}条")

        items, total = search_events(self.db, self.user.id, "关键词E", None, None, 2, 0, mode="keyword")
        self.assertEqual(total, 3)
        self.assertEqual(len(items), 2)

        items2, _ = search_events(self.db, self.user.id, "关键词E", None, None, 2, 2, mode="keyword")
        self.assertEqual(len(items2), 1)

    def test_user_isolation(self):
        other = User(username=f"search_other_{uuid4().hex[:8]}", password_encrypted="x")
        self.db.add(other)
        self.db.flush()
        d_other, o_other = self._make_diary_for_user(other, DiaryStatus.organized, date(2026, 6, 1))
        self._make_event(o_other, "关键词F", ["包含关键词F"], "关键词F 包含关键词F")

        d_me, o_me = self._make_diary(DiaryStatus.organized, date(2026, 6, 2))
        self._make_event(o_me, "关键词F", ["包含关键词F"], "关键词F 包含关键词F")

        items, total = search_events(self.db, self.user.id, "关键词F", None, None, 20, 0, mode="keyword")
        self.assertEqual(total, 1)
        self.assertEqual(items[0]["diary_id"], d_me.id)


@unittest.skip("039 已移除旧事件级融合契约；覆盖已迁至 test_diary_level_search")
class SearchFusionUnitTest(unittest.TestCase):
    """纯函数单元测试（不依赖 PG）：RRF 融合与 LIKE 转义。

    这些函数与数据库 / 向量检索解耦，可在任意环境运行，验证语义增强的核心融合逻辑。
    """

    def test_rrf_fuse_keyword_only(self):
        kw = [("e1", "d1", date(2026, 1, 1)), ("e2", "d1", date(2026, 1, 2))]
        fused, meta = _rrf_fuse(kw, [])
        self.assertEqual(fused, ["e1", "e2"])
        self.assertEqual(meta["e1"], ("d1", date(2026, 1, 1)))

    def test_rrf_fuse_prefers_both_branches(self):
        kw = [("e1", "d1", date(2026, 1, 1)), ("e2", "d1", date(2026, 1, 2))]
        sem = [("e2", "d1", date(2026, 1, 2)), ("e3", "d2", date(2026, 1, 3))]
        fused, _meta = _rrf_fuse(kw, sem)
        # e2 在两分支均第 1，RRF 分最高应排首位。
        self.assertEqual(fused[0], "e2")
        # 全部 3 个事件都应被召回（并集）。
        self.assertEqual(set(fused), {"e1", "e2", "e3"})

    def test_rrf_fuse_score_is_reciprocal_decay(self):
        # 验证 RRF 分数 = Σ 1/(k+rank)，k=60。
        kw = [("e1", "d1", date(2026, 1, 1)), ("e2", "d1", date(2026, 1, 2))]
        sem = [("e2", "d1", date(2026, 1, 2)), ("e3", "d2", date(2026, 1, 3))]
        fused, _meta = _rrf_fuse(kw, sem, k=60)
        # e2：kw rank1 + sem rank1 => 1/61 + 1/61 = 2/61
        # e1：kw rank1 => 1/61；e3：sem rank2 => 1/62
        # 排序应为 e2 > e1(1/61) > e3(1/62)
        self.assertEqual(fused, ["e2", "e1", "e3"])

    def test_escape_like_escapes_wildcards(self):
        self.assertEqual(_escape_like("100% done_"), "100\\% done\\_")
        self.assertEqual(_escape_like("a\\b"), "a\\\\b")


@unittest.skip("039 已替换旧语义块表契约；覆盖已迁至 test_diary_level_search")
class SemanticSearchServiceTest(unittest.TestCase):
    """语义召回分支单测：需 PG + pgvector；无则整体 skip（与 SearchServiceTest 一致）。

    通过 monkeypatch embedding_client.embed_texts 注入确定性查询向量，绕过真实
    百炼 API；直接以 ORM 写入 event_embedding_chunks 向量，验证语义召回排序、
    命中层汇总（matched_chunk_types）、事件级去重与精确 total。
    """

    @classmethod
    def setUpClass(cls):
        _require_vector()

    def setUp(self):
        self.db = SessionLocal()
        self.user = User(username=f"search_sem_{uuid4().hex[:8]}", password_encrypted="x")
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

    def _make_event_with_chunks(self, org, title, body_list, search_text, chunk_vectors):
        event = self._make_event(org, title, body_list, search_text)
        for chunk_type, vec in chunk_vectors.items():
            self.db.add(EventEmbeddingChunk(
                event_id=event.id, chunk_type=chunk_type, content=title, embedding=vec,
            ))
        self.db.flush()
        return event

    def test_semantic_ranking_and_matched_chunk_types(self):
        import math

        d, o = self._make_diary(DiaryStatus.organized, date(2026, 8, 1))

        def unit_vec(seed):
            base = [(seed + i) % 5 - 2 for i in range(1024)]
            norm = math.sqrt(sum(x * x for x in base)) or 1.0
            return [x / norm for x in base]

        q_vec = unit_vec(3)
        e_near = self._make_event_with_chunks(
            o, "语义近邻事件", ["近邻"], "语义近邻事件 近邻",
            {"fact": unit_vec(4), "self_understanding": unit_vec(5)},
        )
        e_far = self._make_event_with_chunks(
            o, "语义远邻事件", ["远邻"], "语义远邻事件 远邻",
            {"fact": unit_vec(80)},
        )

        with patch("services.embedding_client.embed_texts", return_value=[q_vec]):
            items, total = search_events(
                self.db, self.user.id, "语义查询唯一串", None, None, 20, 0, mode="semantic"
            )
        self.assertEqual(total, 2)
        # 最相似事件（余弦距离最小）应排首位。
        self.assertEqual(items[0]["id"], e_near.id)
        # 命中层随结果回传（fact + self_understanding）。
        self.assertIn("fact", items[0]["matched_chunk_types"])
        self.assertIn("self_understanding", items[0]["matched_chunk_types"])
        # 远邻事件仅命中 fact 层（事件级去重：多层命中只计一次事件）。
        far_item = next(it for it in items if it["id"] == e_far.id)
        self.assertEqual(far_item["matched_chunk_types"], ["fact"])

    def test_semantic_isolation_by_user(self):
        import math

        other = User(username=f"search_sem_other_{uuid4().hex[:8]}", password_encrypted="x")
        self.db.add(other)
        self.db.flush()
        d_other, o_other = self._make_diary_for_user(other, DiaryStatus.organized, date(2026, 8, 2))

        def unit_vec(seed):
            base = [(seed + i) % 5 - 2 for i in range(1024)]
            norm = math.sqrt(sum(x * x for x in base)) or 1.0
            return [x / norm for x in base]

        q_vec = unit_vec(3)
        self._make_event_with_chunks(
            o_other, "他人语义事件", ["他人"], "他人语义事件 他人",
            {"fact": unit_vec(4)},
        )

        with patch("services.embedding_client.embed_texts", return_value=[q_vec]):
            items, total = search_events(
                self.db, self.user.id, "他人语义查询唯一串", None, None, 20, 0, mode="semantic"
            )
        # 语义分支同样按 user_id 隔离，不召回他人事件。
        self.assertEqual(total, 0)
        self.assertEqual(items, [])

    def _make_diary_for_user(self, user, status, diary_date):
        diary = Diary(user_id=user.id, original_text="原文", diary_date=diary_date, status=status)
        self.db.add(diary)
        self.db.flush()
        task = OrganizeTask(diary_id=diary.id, user_id=user.id, status="completed", task_type="organize")
        self.db.add(task)
        self.db.flush()
        org = DiaryOrganized(
            diary_id=diary.id, task_id=task.id, title="标题", summary="", content="", mood=None, location=None,
        )
        self.db.add(org)
        self.db.flush()
        return diary, org


@unittest.skip("039 已替换旧语义块表契约；覆盖已迁至 test_diary_level_search")
class EmbeddingPrivacyUnitTest(unittest.TestCase):
    """语义向量调用隐私最小化单测：仅发送文本，绝不携带用户标识。无需 PG / 真实 API。"""

    def test_embedding_client_sends_only_text(self):
        import services.embedding_client as ec

        captured: dict = {}

        class _FakeData:
            def __init__(self, embedding):
                self.embedding = embedding

        class _FakeResp:
            @property
            def data(self):
                return [_FakeData([0.1, 0.2])]

        class _FakeEmbeddings:
            def create(self, **kwargs):
                captured.update(kwargs)
                return _FakeResp()

        class _FakeClient:
            def __init__(self, *args, **kwargs):
                self.embeddings = _FakeEmbeddings()

        fake_config = ec.EmbeddingConfig(
            api_key="test-key",
            api_base_url="https://api.test",
            model_name="qwen3.7-text-embedding",
            dimensions=1024,
        )
        with patch.object(ec, "OpenAI", _FakeClient), patch.object(
            ec, "get_embedding_config", return_value=fake_config
        ):
            result = ec.embed_texts(["仅文本无用户标识"])

        self.assertEqual(result, [[0.1, 0.2]])
        # 出网仅含待向量化文本；不得出现任何用户标识字段。
        self.assertEqual(captured.get("input"), ["仅文本无用户标识"])
        for forbidden in ("user_id", "username", "user", "userId"):
            self.assertNotIn(forbidden, captured)


if __name__ == "__main__":
    unittest.main()
