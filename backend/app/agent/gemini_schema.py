"""Gemini Developer API-compatible schema conversion layer.

Converts Pydantic models and JSON Schema definitions into strict Gemini Developer API
compatible schemas, recursively stripping unsupported `additionalProperties` and
`additional_properties` flags while preserving field types, descriptions, constraints,
enums, defaults, and nullable semantics.
"""

import copy
from typing import Any

from pydantic import BaseModel


def to_gemini_compatible_schema(
    schema_or_model: type[BaseModel] | dict[str, Any],
) -> dict[str, Any]:
    """Convert a Pydantic model class or JSON schema dict into a Gemini Developer API-compatible schema dict.

    Invariants:
    - Never emits `additionalProperties` or `additional_properties` anywhere in the schema tree.
    - Preserves all properties, required fields, $defs, items, anyOf/nullable unions, enums, and descriptions.
    - Post-generation validation remains strictly enforced by Pydantic.
    """
    if isinstance(schema_or_model, type) and issubclass(schema_or_model, BaseModel):
        raw_schema = schema_or_model.model_json_schema()
    elif isinstance(schema_or_model, dict):
        raw_schema = schema_or_model
    else:
        raise TypeError(
            f"Expected BaseModel subclass or schema dict, got {type(schema_or_model)}"
        )

    clean_schema = copy.deepcopy(raw_schema)

    def _sanitize(node: Any) -> None:
        if isinstance(node, dict):
            # Remove unsupported additional properties flags
            node.pop("additionalProperties", None)
            node.pop("additional_properties", None)
            for v in node.values():
                _sanitize(v)
        elif isinstance(node, list):
            for item in node:
                _sanitize(item)

    _sanitize(clean_schema)
    return clean_schema
