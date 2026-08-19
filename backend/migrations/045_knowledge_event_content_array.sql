ALTER TABLE knowledge_atomic_events
    DROP COLUMN source_fragments,
    ALTER COLUMN content TYPE JSONB USING to_jsonb(ARRAY[content]);

ALTER TABLE knowledge_atomic_events
    ADD CONSTRAINT ck_knowledge_atomic_events_content
    CHECK (jsonb_typeof(content) = 'array' AND jsonb_array_length(content) > 0);
