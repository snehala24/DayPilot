import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ExtractedCommitment(BaseModel):
    """Schema for a commitment candidate extracted from raw text."""

    title: str = Field(..., description="Actionable task or commitment title")
    description: str | None = Field(
        None, description="Detailed context or notes for the task"
    )
    due_date: str | None = Field(
        None,
        description="Explicit or resolved date in YYYY-MM-DD format, or None if unknown",
    )
    due_time: str | None = Field(
        None, description="Time in 24h HH:MM format, or None if unknown"
    )
    due_tz: str | None = Field(
        None,
        description="IANA timezone name (e.g. UTC, Asia/Kolkata), or None if unknown",
    )
    priority: int = Field(
        3, ge=1, le=4, description="Priority from 1 (highest/urgent) to 4 (lowest)"
    )
    estimated_duration_minutes: int | None = Field(
        None, ge=1, description="Estimated duration in minutes if specified"
    )
    dependencies: list[str] = Field(
        default_factory=list, description="Titles or references of prerequisite tasks"
    )
    owner: str | None = Field(None, description="Explicit owner/assignee if stated")
    source_span: dict[str, Any] | None = Field(
        None, description="Span in raw text: {start_char, end_char, text}"
    )
    confidence: float = Field(
        1.0, ge=0.0, le=1.0, description="Confidence score for this extraction"
    )
    uncertain_fields: list[str] = Field(
        default_factory=list,
        description="Fields flagged as ambiguous, inferred, or missing",
    )


class RawExtractionResult(BaseModel):
    """Raw output schema from LLM model extraction."""

    commitments: list[ExtractedCommitment] = Field(default_factory=list)


class AmbiguityQuestion(BaseModel):
    """A clarifying question generated when critical info is missing or ambiguous."""

    id: str = Field(..., description="Unique question identifier")
    commitment_title: str | None = Field(
        None, description="Title of the affected commitment"
    )
    field: str = Field(
        ...,
        description="The field requiring clarification (e.g. due_date, timezone, owner)",
    )
    question: str = Field(..., description="Human-readable clarifying question")
    options: list[str] | None = Field(
        None, description="Suggested answers or alternatives"
    )
    source_text_snippet: str | None = Field(
        None, description="Relevant text snippet triggering the question"
    )


class ExtractionReview(BaseModel):
    """Response payload for review before commitments are confirmed."""

    note_id: uuid.UUID
    raw_text: str
    commitments: list[ExtractedCommitment]
    questions: list[AmbiguityQuestion]
    can_confirm_all: bool = Field(
        ...,
        description="True only when all candidates have no unresolved critical questions",
    )


class RawInputRequest(BaseModel):
    """Payload submitted to POST /api/v1/inputs."""

    raw_text: str = Field(
        ..., min_length=1, description="Raw unstructured note or text input"
    )
    project_id: uuid.UUID | None = Field(
        None, description="Optional project to link the note and commitments to"
    )
    user_timezone: str | None = Field(
        None, description="User's IANA timezone; falls back to user setting"
    )


class ConfirmedCommitmentInput(BaseModel):
    """User-reviewed commitment candidate ready to be saved."""

    title: str = Field(..., min_length=1)
    description: str | None = None
    due_date: str | None = None
    due_time: str | None = None
    due_tz: str | None = None
    priority: int = Field(3, ge=1, le=4)
    estimate_minutes: int | None = Field(None, ge=1)
    owner: str | None = None
    dependencies: list[str] = Field(default_factory=list)
    source_span: dict[str, Any] | None = None

    @field_validator("due_date")
    @classmethod
    def validate_due_date_format(cls, v: str | None) -> str | None:
        if v:
            try:
                datetime.strptime(v, "%Y-%m-%d")
            except ValueError:
                raise ValueError("due_date must be in YYYY-MM-DD format")
        return v

    @field_validator("due_time")
    @classmethod
    def validate_due_time_format(cls, v: str | None) -> str | None:
        if v:
            try:
                datetime.strptime(v, "%H:%M")
            except ValueError:
                raise ValueError("due_time must be in HH:MM (24-hour) format")
        return v


class ConfirmCommitmentsRequest(BaseModel):
    """Payload submitted to POST /api/v1/commitments/confirm."""

    note_id: uuid.UUID = Field(..., description="ID of the original note")
    project_id: uuid.UUID | None = Field(
        None, description="Project ID to assign commitments to"
    )
    commitments: list[ConfirmedCommitmentInput] = Field(
        ..., min_length=1, description="List of confirmed commitments"
    )
    idempotency_key: str | None = Field(
        None, max_length=128, description="Client idempotency key"
    )


class ConfirmedCommitmentItem(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None
    due_at: datetime | None
    due_tz: str | None
    priority: int
    status: str
    owner: str | None
    estimate_minutes: int | None
    source_note_id: uuid.UUID | None
    dependencies: list[uuid.UUID]


class ConfirmCommitmentsResponse(BaseModel):
    """Response returned upon successful confirmation."""

    note_id: uuid.UUID
    confirmed_commitment_ids: list[uuid.UUID]
    commitments: list[ConfirmedCommitmentItem]
    audit_event_id: uuid.UUID
    status: str = "confirmed"
