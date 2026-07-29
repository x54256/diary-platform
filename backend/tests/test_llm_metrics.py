from types import SimpleNamespace

from services.llm_metrics import prompt_token_count


def test_prompt_tokens_prefer_provider_usage_metadata():
    response = SimpleNamespace(
        usage_metadata={"input_tokens": 123},
        response_metadata={},
    )

    assert prompt_token_count(response, "unknown-model", "system", "user") == (123, "usage")


def test_prompt_tokens_support_openai_response_dict():
    response = {"usage": {"prompt_tokens": 45}}

    assert prompt_token_count(response, "unknown-model", "system", "user") == (45, "usage")


def test_prompt_tokens_fall_back_to_tiktoken_estimate():
    response = SimpleNamespace(usage_metadata=None, response_metadata={})

    tokens, source = prompt_token_count(response, "unknown-model", "system", "user")

    assert tokens > 0
    assert source == "estimated"
