import pytest
from pydantic import BaseModel

from app.agent.client import (
    FakeLLMClient,
    GeminiLLMClient,
    LLMClientError,
    LLMRateLimitError,
    LLMTimeoutError,
)


class DummySchema(BaseModel):
    name: str
    count: int = 1


def test_fake_llm_client_canned_response():
    client = FakeLLMClient()
    client.set_canned_response("alpha", DummySchema(name="alpha", count=5))

    res = client.generate_structured("Please process alpha prompt", DummySchema)
    assert res.name == "alpha"
    assert res.count == 5
    assert len(client.call_history) == 1


def test_fake_llm_client_failure_injection():
    client = FakeLLMClient()
    client.set_failure(LLMTimeoutError("Request timed out after 10s"))

    with pytest.raises(LLMTimeoutError):
        client.generate_structured("test prompt", DummySchema)


def test_fake_llm_client_rate_limit():
    client = FakeLLMClient()
    client.set_failure(LLMRateLimitError("Quota exceeded (429)"))

    with pytest.raises(LLMRateLimitError):
        client.generate_structured("test prompt", DummySchema)


def test_gemini_client_missing_key_error():
    client = GeminiLLMClient(api_key=None)
    with pytest.raises(LLMClientError) as exc_info:
        client.generate_structured("prompt", DummySchema)
    assert "GEMINI_API_KEY is not set" in str(exc_info.value)
