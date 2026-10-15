"""独立临时数据库中的真实迁移和共享数据保护测试。"""

import os
import unittest
from uuid import uuid4

from sqlalchemy import create_engine, text, inspect
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

import models
from database import Base
from models.model_config import ApiChannel, ChannelModel, ModelCatalog, ModelSetting, ModelStepSetting
from scripts.migrate_event_graph import apply, check, NEW_TABLES, OLD_TABLES


@unittest.skipUnless(os.environ.get("GRAPH_TEST_DATABASE_URL"), "需本机隔离数据库")
class GraphMigrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url = make_url(os.environ["GRAPH_TEST_DATABASE_URL"])
        if url.host != "127.0.0.1" or url.port != 55439 or url.database != "graph_test":
            raise RuntimeError("拒绝非隔离数据库")
        admin = create_engine(url, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            if not connection.execute(text("SELECT 1 FROM pg_database WHERE datname='graph_migration_test'")).scalar():
                connection.exec_driver_sql("CREATE DATABASE graph_migration_test")
        admin.dispose()
        cls.engine = create_engine(url.set(database="graph_migration_test"))

    def setUp(self):
        with self.engine.begin() as connection:
            connection.exec_driver_sql("DROP SCHEMA public CASCADE; CREATE SCHEMA public; CREATE EXTENSION vector")
        shared = [t for t in Base.metadata.sorted_tables if t.name not in NEW_TABLES]
        # 模拟050之前的源事件列，复用所有实际共享表定义。
        Base.metadata.create_all(self.engine, tables=shared)
        with self.engine.begin() as connection:
            connection.exec_driver_sql("ALTER TABLE diary_events DROP COLUMN is_in_graph")
            connection.exec_driver_sql("""
                CREATE TABLE knowledge_tasks(id UUID PRIMARY KEY,status TEXT);
                CREATE TABLE knowledge_deposits(id UUID PRIMARY KEY,task_id UUID REFERENCES knowledge_tasks);
                CREATE TABLE knowledge_matters(id UUID PRIMARY KEY);
                CREATE TABLE knowledge_atomic_events(id UUID PRIMARY KEY,deposit_id UUID REFERENCES knowledge_deposits,matter_id UUID REFERENCES knowledge_matters);
                CREATE TABLE knowledge_event_reviews(id UUID PRIMARY KEY,event_id UUID REFERENCES knowledge_atomic_events,task_id UUID REFERENCES knowledge_tasks);
            """)
        with Session(self.engine) as db:
            catalog = ModelCatalog(id=uuid4(), model_type="language", provider_name="隔离", model_name="migration-test", reasoning_mode="unsupported",
                ability_tier="T1", ability_category="通用对话", original_category="隔离", core_features="隔离",
                scenarios="隔离", score=1, score_label="隔离")
            channel = ApiChannel(id=uuid4(), name="隔离渠道", api_base_url="https://example.test", api_key_encrypted="隔离占位")
            db.add_all([catalog, channel]); db.flush()
            cm = ChannelModel(id=uuid4(), channel_id=channel.id, model_id=catalog.id)
            db.add(cm); db.flush()
            db.add_all([ModelSetting(setting_key="knowledge", channel_model_id=cm.id),
                        ModelSetting(setting_key="analysis", channel_model_id=cm.id),
                        ModelStepSetting(step_key="knowledge_event_extract", channel_model_id=cm.id)])
            db.commit()

    def test_apply_is_transactional_verified_and_idempotent(self):
        with self.engine.begin() as connection:
            before = check(connection)
            self.assertFalse(before["migrated"])
            result = apply(connection)
            self.assertTrue(result["migrated"]); self.assertEqual(result["structure_errors"], [])
        with self.engine.begin() as connection:
            self.assertTrue(apply(connection)["migrated"])
            self.assertEqual(connection.execute(text("SELECT count(*) FROM model_settings WHERE setting_key='analysis'")).scalar(), 1)
            self.assertEqual(connection.execute(text("SELECT count(*) FROM api_channels")).scalar(), 1)
            self.assertEqual(connection.execute(text("SELECT count(*) FROM model_settings WHERE setting_key='knowledge'")).scalar(), 0)
            self.assertTrue(set(OLD_TABLES).isdisjoint(inspect(connection).get_table_names()))

    def test_active_old_task_prevents_any_drop(self):
        with self.engine.begin() as connection:
            connection.execute(text("INSERT INTO knowledge_tasks VALUES(:id,'RUNNING')"), {"id": uuid4()})
        with self.assertRaises(RuntimeError):
            with self.engine.begin() as connection: apply(connection)
        with self.engine.connect() as connection:
            self.assertTrue(inspect(connection).has_table("knowledge_tasks"))
            self.assertFalse(inspect(connection).has_table("graph_tasks"))

    def test_defaults_bind_all_graph_roles_to_flash_with_explicit_thinking(self):
        with Session(self.engine) as db:
            model = db.query(ModelCatalog).one()
            model.model_name, model.reasoning_mode = "qwen3.7-flash-2026-07-15", "switchable"
            channel = ApiChannel(id=uuid4(), name="显式思考渠道", api_base_url="https://example.test",
                api_key_encrypted="隔离占位", thinkmode={"enabled": {"enable_thinking": True}})
            db.add(channel); db.flush()
            binding = ChannelModel(id=uuid4(), channel_id=channel.id, model_id=model.id)
            db.add(binding); db.commit(); expected_id = binding.id
        with self.engine.begin() as connection: apply(connection)
        with Session(self.engine) as db:
            root = db.query(ModelSetting).filter(ModelSetting.setting_key == "graph").one()
            stages = db.query(ModelStepSetting).filter(ModelStepSetting.step_key.like("graph_%")).all()
            self.assertEqual(root.channel_model_id, expected_id)
            self.assertTrue(root.thinking_enabled)
            self.assertEqual(len(stages), 6)
            self.assertTrue(all(s.channel_model_id == expected_id and s.thinking_enabled for s in stages))
