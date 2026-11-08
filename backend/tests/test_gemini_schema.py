"""Tests for Gemini Developer API schema compatibility, conversion, and validation."""

import json
from typing import Any
from unittest.mock import MagicMock

import pytest
from google.genai import Client
from google.genai._transformers import process_schema
from pydantic import BaseModel, Field, ValidationError

from app.agent.client import (
    GeminiLLMClient,
)
from app.agent.gemini_schema import to_gemini_compatible_schema
from app.agent.schemas import (
    ExtractedCommitment,
    RawExtractionResult,
    SourceSpan,
)


class SubModel(BaseModel):
    name: str = Field(..., description="Submodel name")
    tag: str | None = Field(None, description="Optional tag")


class ComplexNestedModel(BaseModel):
    id: str = Field(..., description="Unique ID")
    items: list[SubModel] = Field(default_factory=list, description="List of submodels")
    mapping: dict[str, Any] | None = Field(None, description="Arbitrary mapping")
    optional_int: int | None = Field(None, description="Nullable integer")


def _has_additional_properties(node: Any) -> bool:
    """Recursively search for additionalProperties or additional_properties."""
    if isinstance(node, dict):
        if "additionalProperties" in node or "additional_properties" in node:
            return True
        return any(_has_additional_properties(v) for v in node.values())
    elif isinstance(node, list):
        return any(_has_additional_properties(item) for item in node)
    return False


def test_recursive_schema_compatibility_strips_additional_properties():
    """Verify to_gemini_compatible_schema strips additionalProperties at all nesting levels."""
    raw_schema = ComplexNestedModel.model_json_schema()
    assert _has_additional_properties(raw_schema) is True

    clean_schema = to_gemini_compatible_schema(ComplexNestedModel)
    assert _has_additional_properties(clean_schema) is False
    assert clean_schema["type"] == "object"
    assert "items" in clean_schema["properties"]
    assert "id" in clean_schema["required"]


def test_google_genai_process_schema_accepts_clean_extraction_schema():
    """Verify that the official Google GenAI SDK process_schema accepts our schema without enterprise errors."""
    client = Client(api_key="mock-key-for-offline-transformer-testing")
    clean_schema = to_gemini_compatible_schema(RawExtractionResult)

    # In mldev mode (non-vertexai), process_schema raises ValueError if additionalProperties is present.
    # It must execute without error.
    process_schema(clean_schema, client)

    # Check that core properties and required fields are preserved
    assert "commitments" in clean_schema["properties"]
    assert clean_schema["properties"]["commitments"]["type"].lower() == "array"


def test_sourcespan_model_integration_and_validation():
    """Verify SourceSpan preserves fields and integrates cleanly with ExtractedCommitment."""
    span_data = {"start_char": 5, "end_char": 25, "text": "submit quarterly report"}
    span = SourceSpan.model_validate(span_data)
    assert span.start_char == 5
    assert span.end_char == 25
    assert span.text == "submit quarterly report"

    commitment = ExtractedCommitment(
        title="Submit report",
        source_span=span,
    )
    assert commitment.source_span.start_char == 5

    # Backwards compatibility: dict input auto-validates to SourceSpan
    commitment_from_dict = ExtractedCommitment(
        title="Submit report",
        source_span={"start_char": 10, "end_char": 20, "text": "submit report"},
    )
    assert isinstance(commitment_from_dict.source_span, SourceSpan)
    assert commitment_from_dict.source_span.start_char == 10


def test_malformed_gemini_response_rejected_by_pydantic():
    """Verify malformed JSON or missing required fields are rejected by Pydantic validation."""
    # 1. Missing required field 'title' in commitment
    invalid_data = {
        "commitments": [
            {
                "due_date": "2026-11-15",
                "priority": 2,
            }
        ]
    }
    with pytest.raises(ValidationError):
        RawExtractionResult.model_validate(invalid_data)

    # 2. Invalid priority range (> 4)
    invalid_priority = {
        "commitments": [
            {
                "title": "Invalid task",
                "priority": 99,
            }
        ]
    }
    with pytest.raises(ValidationError):
        RawExtractionResult.model_validate(invalid_priority)


def test_valid_gemini_response_parsed_successfully():
    """Verify a valid JSON response parses cleanly into RawExtractionResult with all fields intact."""
    valid_json = """
    {
      "commitments": [
        {
          "title": "Review marketing copy",
          "description": "Final proofreading before publication",
          "due_date": "2026-11-12",
          "due_time": "14:00",
          "due_tz": "UTC",
          "priority": 1,
          "estimated_duration_minutes": 45,
          "dependencies": ["Draft copy"],
          "owner": "Priya",
          "confidence": 0.95,
          "uncertain_fields": []
        }
      ]
    }
    """
    data = json.loads(valid_json)
    result = RawExtractionResult.model_validate(data)
    assert len(result.commitments) == 1
    c = result.commitments[0]
    assert c.title == "Review marketing copy"
    assert c.due_date == "2026-11-12"
    assert c.due_time == "14:00"
    assert c.priority == 1
    assert c.owner == "Priya"
    assert c.dependencies == ["Draft copy"]


def test_gemini_client_generate_structured_uses_compatible_schema():
    """Verify GeminiLLMClient converts schema before passing to SDK and validates result."""
    client = GeminiLLMClient(api_key="mock-api-key")
    mock_genai_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = json.dumps(
        {
            "commitments": [
                {
                    "title": "Prepare slide deck",
                    "due_date": "2026-11-10",
                    "priority": 2,
                }
            ]
        }
    )
    mock_genai_client.models.generate_content.return_value = mock_response
    client._client = mock_genai_client

    result = client.generate_structured(
        prompt="Prepare slide deck for meeting",
        response_schema=RawExtractionResult,
    )

    assert isinstance(result, RawExtractionResult)
    assert len(result.commitments) == 1
    assert result.commitments[0].title == "Prepare slide deck"

    # Verify that the schema passed to SDK config has NO additionalProperties
    call_args = mock_genai_client.models.generate_content.call_args
    passed_config = call_args.kwargs["config"]
    assert _has_additional_properties(passed_config.response_schema) is False


def test_live_gemini_client_structured_extraction():
    """Verify live Gemini Developer API structured output when network and API key are available."""
    from app.config import settings

    if not settings.GEMINI_API_KEY:
        pytest.skip("Live GEMINI_API_KEY not configured in environment.")

    client = GeminiLLMClient(
        api_key=settings.GEMINI_API_KEY,
        model_name=settings.LLM_MODEL,
    )

    try:
        res = client.generate_structured(
            prompt="Extract commitments from: Deliver proposal by 2026-11-20 18:00 UTC.",
            response_schema=RawExtractionResult,
        )
        assert isinstance(res, RawExtractionResult)
        assert len(res.commitments) >= 1
        assert "proposal" in res.commitments[0].title.lower()
    except Exception as e:
        # If running inside sandbox with blocked network, skip gracefully
        if "getaddrinfo failed" in str(e) or "connecterror" in str(e).lower():
            pytest.skip("Network access blocked in current environment sandbox.")
        raise

