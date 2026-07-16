-- 为分析任务记录固定的执行模式，确保失败重试不会切换到另一条 LangGraph 流程。
ALTER TABLE organize_tasks
    ADD COLUMN IF NOT EXISTS analysis_mode VARCHAR(20);

-- 历史分析任务均属于普通分析；整理任务保持 NULL。
UPDATE organize_tasks
SET analysis_mode = 'ordinary'
WHERE task_type = 'analyze'
  AND analysis_mode IS NULL;
