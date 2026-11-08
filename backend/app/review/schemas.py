import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field


class CommitmentReviewItem(BaseModel):
    id: uuid.UUID
    title: str
    priority: int
    status: str
    due_at: datetime | None = None
    estimate_minutes: int | None = None


class ConflictReviewItem(BaseModel):
    id: uuid.UUID
    commitment_id: uuid.UUID
    commitment_title: str
    kind: str
    reason: str | None = None
    alternatives_count: int


class ProposalReviewItem(BaseModel):
    id: uuid.UUID
    title: str
    kind: str
    status: str
    expires_at: datetime | None = None


class ReminderAttentionItem(BaseModel):
    id: uuid.UUID
    commitment_id: uuid.UUID
    commitment_title: str | None = None
    status: str
    attempt_count: int
    due_at: datetime
    last_error: str | None = None


class DailyReviewResponse(BaseModel):
    review_date: date
    timezone: str = "UTC"
    factual_metrics: dict[str, int] = Field(
        default_factory=dict,
        description="Exact count of factual items observed in persisted state",
    )
    completed_today: list[CommitmentReviewItem] = Field(default_factory=list)
    scheduled_uncompleted: list[CommitmentReviewItem] = Field(default_factory=list)
    overdue: list[CommitmentReviewItem] = Field(default_factory=list)
    unresolved_conflicts: list[ConflictReviewItem] = Field(default_factory=list)
    pending_proposals: list[ProposalReviewItem] = Field(default_factory=list)
    reminders_needing_attention: list[ReminderAttentionItem] = Field(
        default_factory=list
    )
    suggested_actions: list[str] = Field(default_factory=list)
    narrative_summary: str | None = None
