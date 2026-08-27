-- 知识库存量逐篇升级：knowledge_tasks 增加任务类型。
--
-- DEPOSIT 沉淀任务（走完整 LangGraph 图）；UPGRADE 升级任务（不走图，直接对
-- 已完成 ATOMIC_EVENTS 的日记执行事项匹配，见知识库事项管理设计 §5.4）。

ALTER TABLE knowledge_tasks
    ADD COLUMN IF NOT EXISTS task_type VARCHAR(16) NOT NULL DEFAULT 'DEPOSIT';

ALTER TABLE knowledge_tasks DROP CONSTRAINT IF EXISTS ck_knowledge_tasks_type;
ALTER TABLE knowledge_tasks
    ADD CONSTRAINT ck_knowledge_tasks_type CHECK (task_type IN ('DEPOSIT','UPGRADE'));
