-- LLM 调用性能和 token 统计

CREATE TABLE IF NOT EXISTS llm_call_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    step_name VARCHAR(100) NOT NULL,
    model_name VARCHAR(200),
    prompt_tokens INTEGER NOT NULL,
    prompt_tokens_source VARCHAR(20) NOT NULL,
    duration_ms INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL,
    error_type VARCHAR(100),
    request_id VARCHAR(100),
    chain_id VARCHAR(100)
);

CREATE INDEX IF NOT EXISTS idx_llm_call_logs_duration
    ON llm_call_logs(duration_ms DESC);

CREATE INDEX IF NOT EXISTS idx_llm_call_logs_created_at
    ON llm_call_logs(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_llm_call_logs_step_duration
    ON llm_call_logs(step_name, duration_ms DESC);
