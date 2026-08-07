-- 存量数据回填：对所有 diary_events 重算 search_text。
--
-- 触发器（见 036）会在事件字段或关联分析内容变更时自动维护 search_text；
-- 本脚本仅用于补齐迁移前已存在的历史数据。执行一次即可，重复执行幂等。

SELECT compute_event_search_vector(id)
FROM diary_events;
