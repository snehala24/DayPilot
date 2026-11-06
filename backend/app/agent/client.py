import abc
import json
import logging
from typing import Any

from pydantic import BaseModel, ValidationError

logger = logging.getLogger("daypilot.agent.client")


class LLMClientError(Exception):
    """Base exception for LLM client errors."""


class LLMTimeoutError(LLMClientError):
    """Raised when an LLM call times out."""


class LLMRateLimitError(LLMClientError):
    """Raised when LLM quota or rate limit is hit."""


class LLMMalformedResponseError(LLMClientError):
    """Raised when LLM response cannot be parsed or validated."""


class LLMClient(abc.ABC):
    """Provider-independent interface for LLM operations.

    Invariants:
    - LLM clients never access database operations or external-write tools.
    - Every response must be validated against a Pydantic schema before returning.
    """

    @abc.abstractmethod
    def generate_structured(
        self,
        prompt: str,
        response_schema: type[BaseModel],
        system_instruction: str | None = None,
    ) -> BaseModel:
        """Generate structured output validated against a Pydantic schema."""


class FakeLLMClient(LLMClient):
    """Deterministic, mock LLM client for testing and synthetic evaluation."""

    def __init__(self, canned_responses: dict[str, BaseModel] | None = None):
        self.canned_responses: dict[str, BaseModel] = canned_responses or {}
        self.call_history: list[dict[str, Any]] = []
        self.should_fail_with: Exception | None = None

    def set_canned_response(self, prompt_substring: str, response: BaseModel) -> None:
        self.canned_responses[prompt_substring] = response

    def set_failure(self, exception: Exception | None) -> None:
        self.should_fail_with = exception

    def generate_structured(
        self,
        prompt: str,
        response_schema: type[BaseModel],
        system_instruction: str | None = None,
    ) -> BaseModel:
        self.call_history.append(
            {
                "prompt": prompt,
                "response_schema": response_schema.__name__,
                "system_instruction": system_instruction,
            }
        )

        if self.should_fail_with:
            raise self.should_fail_with

        # Search for matching substring in canned responses (case-insensitive)
        prompt_lower = prompt.lower()
        for key, response in self.canned_responses.items():
            if key.lower() in prompt_lower:
                if isinstance(response, response_schema):
                    return response
                elif isinstance(response, dict):
                    return response_schema.model_validate(response)
                elif isinstance(response, str):
                    try:
                        data = json.loads(response)
                        return response_schema.model_validate(data)
                    except Exception as e:
                        raise LLMMalformedResponseError(
                            f"Failed to parse canned JSON response: {e}"
                        ) from e

        # If no canned response matches, attempt to synthesize an empty or default schema instance
        try:
            return response_schema.model_validate({})
        except ValidationError as e:
            raise LLMMalformedResponseError(
                f"No canned response matched prompt and schema {response_schema.__name__} has required fields: {e}"
            ) from e


class GeminiLLMClient(LLMClient):
    """Official Google GenAI client for Gemini models."""

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str = "gemini-2.5-flash",
    ):
        self.api_key = api_key
        self.model_name = model_name
        self._client = None

    def _get_client(self):
        if self._client is None:
            if not self.api_key:
                raise LLMClientError(
                    "GEMINI_API_KEY is not set or empty. Cannot initialize Gemini client."
                )
            try:
                from google import genai

                self._client = genai.Client(api_key=self.api_key)
            except Exception as e:
                raise LLMClientError(
                    f"Failed to initialize google.genai Client: {e}"
                ) from e
        return self._client

    def generate_structured(
        self,
        prompt: str,
        response_schema: type[BaseModel],
        system_instruction: str | None = None,
    ) -> BaseModel:
        client = self._get_client()
        try:
            from google.genai import types

            config = types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=response_schema,
                system_instruction=system_instruction,
                temperature=0.0,
            )

            response = client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=config,
            )

            raw_text = response.text
            if not raw_text:
                raise LLMMalformedResponseError(
                    "Received empty response from Gemini API."
                )

            data = json.loads(raw_text)
            return response_schema.model_validate(data)

        except ValidationError as e:
            raise LLMMalformedResponseError(
                f"Model output failed Pydantic validation: {e}"
            ) from e
        except json.JSONDecodeError as e:
            raise LLMMalformedResponseError(
                f"Model output is not valid JSON: {e}"
            ) from e
        except Exception as e:
            error_str = str(e).lower()
            if "timeout" in error_str or "deadline" in error_str:
                raise LLMTimeoutError(f"Gemini API call timed out: {e}") from e
            elif (
                "quota" in error_str or "rate limit" in error_str or "429" in error_str
            ):
                raise LLMRateLimitError(f"Gemini API rate limit exceeded: {e}") from e
            raise LLMClientError(f"Gemini API call failed: {e}") from e


_override_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """Return configured LLM client: override -> Gemini (if configured) -> Fake."""
    global _override_client
    if _override_client is not None:
        return _override_client

    from app.config import settings

    if settings.GEMINI_API_KEY:
        return GeminiLLMClient(
            api_key=settings.GEMINI_API_KEY,
            model_name=settings.LLM_MODEL,
        )
    return FakeLLMClient()


def set_llm_client_override(client: LLMClient | None) -> None:
    """Override LLM client (used for tests and benchmarks)."""
    global _override_client
    _override_client = client
