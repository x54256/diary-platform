-- 统一搜索（方案 B）：在 diary_events 上维护触发器聚合的检索文本列 search_text，
-- 使用 pg_trgm 贡献扩展做子串匹配（ILIKE）与相关度排序（similarity）。
--
-- 当用户环境无法安装中文分词扩展 zhparser 时，回退到此方案。pg_trgm 为 PG 内置
-- contrib 扩展，通常随服务端安装；如报权限不足，需由 DBA 预装后再执行本迁移。

-- 1. 启用 pg_trgm（内置 contrib，提供 similarity / ILIKE 的 trigram 加速与 gin_trgm_ops）
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 2. 新增检索文本列（触发器维护，允许为空以兼容尚未回填的历史数据）
ALTER TABLE diary_events ADD COLUMN IF NOT EXISTS search_text TEXT;

-- 3. GIN trigram 索引，加速 ILIKE / similarity 查询
CREATE INDEX IF NOT EXISTS ix_diary_events_search_text
    ON diary_events USING GIN (search_text gin_trgm_ops);

-- 4. 触发器函数：聚合「事件自身字段 + 关联 CURRENT 轮次 EVENT 作用域分析内容」
--    检索范围仅含事件内容（event_title/body/feeling/reflection）与关联分析（content/question），
--    不检索 event_tags（标签仅展示）。body/feeling/reflection 以 JSON 数组存储，提取纯文本。
CREATE OR REPLACE FUNCTION compute_event_search_vector(p_event_id UUID)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    v_search_text     TEXT := '';
    v_diary_id        UUID;
    v_current_run_id  UUID;
BEGIN
    -- 4.1 收集事件自身字段（JSON 数组字段解析为纯文本，避免把 JSON 括号/引号写进检索文本）
    SELECT
        COALESCE(e.event_title, '') || ' ' ||
        COALESCE(
            CASE WHEN e.body IS NOT NULL
                 THEN (SELECT COALESCE(string_agg(value::text, ' '), '') FROM json_array_elements_text(e.body::json))
                 ELSE '' END
        , '') || ' ' ||
        COALESCE(
            CASE WHEN e.feeling IS NOT NULL
                 THEN (SELECT COALESCE(string_agg(value::text, ' '), '') FROM json_array_elements_text(e.feeling::json))
                 ELSE '' END
        , '') || ' ' ||
        COALESCE(
            CASE WHEN e.reflection IS NOT NULL
                 THEN (SELECT COALESCE(string_agg(value::text, ' '), '') FROM json_array_elements_text(e.reflection::json))
                 ELSE '' END
        , '')
    INTO v_search_text
    FROM diary_events e
    WHERE e.id = p_event_id;

    v_search_text := COALESCE(v_search_text, '');

    -- 4.2 定位事件所属日记，取 CURRENT 分析轮次
    -- 注意：do 是 PostgreSQL 保留关键字，不能作为表别名，改用 dorg。
    SELECT dorg.diary_id INTO v_diary_id
    FROM diary_events e
    JOIN diary_organized dorg ON dorg.id = e.diary_organized_id
    WHERE e.id = p_event_id;

    SELECT ar.id INTO v_current_run_id
    FROM analysis_runs ar
    WHERE ar.diary_id = v_diary_id
      AND ar.status = 'CURRENT'
    ORDER BY ar.created_at DESC
    LIMIT 1;

    -- 4.3 聚合关联 EVENT 作用域分析内容（仅 CURRENT 轮次，覆盖全部 7 种分析类型）
    IF v_current_run_id IS NOT NULL THEN
        SELECT v_search_text || ' ' || COALESCE(
            string_agg(COALESCE(ai.content, '') || ' ' || COALESCE(ai.question, ''), ' '
        ), '')
        INTO v_search_text
        FROM analysis_items ai
        WHERE ai.analysis_run_id = v_current_run_id
          AND ai.scope = 'EVENT'
          AND ai.event_id = p_event_id;
        v_search_text := COALESCE(v_search_text, '');
    END IF;

    UPDATE diary_events SET search_text = v_search_text WHERE id = p_event_id;
END;
$$;

-- 5a. 事件自身字段变更时重算检索文本
CREATE OR REPLACE FUNCTION trg_event_search_vector_on_event()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM compute_event_search_vector(NEW.id);
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS event_search_vector_event_tg ON diary_events;
CREATE TRIGGER event_search_vector_event_tg
    AFTER INSERT OR UPDATE OF event_title, body, feeling, reflection
    ON diary_events
    FOR EACH ROW
    EXECUTE FUNCTION trg_event_search_vector_on_event();

-- 5b. 关联分析内容变更时重算对应事件的检索文本
CREATE OR REPLACE FUNCTION trg_event_search_vector_on_analysis()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_event_id UUID;
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_event_id := OLD.event_id;
    ELSE
        v_event_id := NEW.event_id;
    END IF;
    -- event_id 为空（DIARY 作用域分析）不参与事件检索，直接跳过
    IF v_event_id IS NOT NULL THEN
        PERFORM compute_event_search_vector(v_event_id);
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS event_search_vector_analysis_tg ON analysis_items;
CREATE TRIGGER event_search_vector_analysis_tg
    AFTER INSERT OR UPDATE OF content, question OR DELETE
    ON analysis_items
    FOR EACH ROW
    EXECUTE FUNCTION trg_event_search_vector_on_analysis();
