import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.integrations.notifications import (
    SimulatedNotificationAdapter,
)
from app.models.database import get_db
from app.models.entities import DeliveryAttempt, Reminder
from app.reminders.manager import (
    ReminderManager,
    ReminderNotFoundError,
    ReminderStateError,
    RetryPolicy,
)
from app.reminders.worker import ReminderDispatcher

router = APIRouter(prefix="/reminders", tags=["Reminders & Notifications"])


class CreateReminderRequest(BaseModel):
    commitment_id: uuid.UUID = Field(..., description="Commitment to remind about")
    due_at: datetime = Field(
        ..., description="When the reminder should be sent (UTC or ISO with timezone)"
    )
    channel: str = Field(
        "in_app",
        description="Delivery channel (e.g. in_app, simulated_sms, simulated_email)",
    )
    idempotency_key: str | None = Field(
        None, description="Client idempotency key to prevent duplicate creation"
    )


class DeliveryAttemptItem(BaseModel):
    id: uuid.UUID
    attempted_at: datetime
    outcome: str
    error: str | None = None
    created_at: datetime


class ReminderResponse(BaseModel):
    id: uuid.UUID
    commitment_id: uuid.UUID
    due_at: datetime
    channel: str
    status: str
    attempt_count: int
    idempotency_key: str
    created_at: datetime
    updated_at: datetime


class ReminderDetailResponse(ReminderResponse):
    delivery_attempts: list[DeliveryAttemptItem] = []


class DispatchRequest(BaseModel):
    simulated_mode: str | None = Field(
        None,
        description="Fault injection mode: success, transient_error, permanent_error, intermittent",
    )
    batch_size: int = Field(
        50, ge=1, le=500, description="Max reminders to process in this run"
    )


class DispatchResponse(BaseModel):
    processed_count: int
    delivered_count: int
    retried_count: int
    failed_count: int
    recovered_count: int
    skipped_count: int
    details: list[dict[str, Any]]


@router.post("", response_model=ReminderResponse, status_code=status.HTTP_201_CREATED)
def create_reminder(
    req: CreateReminderRequest,
    db: Session = Depends(get_db),
):
    """Create a new scheduled reminder with idempotency and timezone handling."""
    manager = ReminderManager(db=db)
    try:
        reminder = manager.create_reminder(
            commitment_id=req.commitment_id,
            due_at=req.due_at,
            channel=req.channel,
            idempotency_key=req.idempotency_key,
        )
        return _build_reminder_response(reminder)
    except ReminderNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("", response_model=list[ReminderResponse])
def list_reminders(
    status: str | None = Query(
        None,
        description="Filter by status (scheduled, claimed, retrying, delivered, needs_attention, cancelled)",
    ),
    commitment_id: uuid.UUID | None = Query(
        None, description="Filter by commitment ID"
    ),
    db: Session = Depends(get_db),
):
    """List reminders with optional status and commitment filters."""
    query = db.query(Reminder)
    if isinstance(status, str):
        query = query.filter(Reminder.status == status)
    if isinstance(commitment_id, uuid.UUID):
        query = query.filter(Reminder.commitment_id == commitment_id)

    reminders = query.order_by(Reminder.due_at.asc()).all()
    return [_build_reminder_response(r) for r in reminders]


@router.get("/{reminder_id}", response_model=ReminderDetailResponse)
def get_reminder(
    reminder_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """Retrieve full details for a reminder including all delivery attempts."""
    manager = ReminderManager(db=db)
    try:
        reminder = manager.get_reminder(reminder_id)
        attempts = (
            db.query(DeliveryAttempt)
            .filter(DeliveryAttempt.reminder_id == reminder.id)
            .order_by(DeliveryAttempt.attempted_at.asc())
            .all()
        )
        attempt_items = [
            DeliveryAttemptItem(
                id=a.id,
                attempted_at=a.attempted_at,
                outcome=a.outcome,
                error=a.error,
                created_at=a.created_at,
            )
            for a in attempts
        ]
        resp = _build_reminder_response(reminder)
        return ReminderDetailResponse(
            **resp.model_dump(),
            delivery_attempts=attempt_items,
        )
    except ReminderNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/{reminder_id}/cancel", response_model=ReminderResponse)
def cancel_reminder(
    reminder_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """Cancel a scheduled or retrying reminder."""
    manager = ReminderManager(db=db)
    try:
        reminder = manager.cancel_reminder(reminder_id)
        return _build_reminder_response(reminder)
    except ReminderNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ReminderStateError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/dispatch", response_model=DispatchResponse)
def dispatch_due_reminders(
    req: DispatchRequest | None = None,
    db: Session = Depends(get_db),
):
    """Controlled worker entry point to process due reminders.

    Supports fault injection for deterministic testing and safe repeated requests.
    """
    req = req or DispatchRequest()
    mode = req.simulated_mode or "success"
    adapter = SimulatedNotificationAdapter(default_mode=mode)
    dispatcher = ReminderDispatcher(
        db=db,
        adapter=adapter,
        retry_policy=RetryPolicy(),
    )

    summary = dispatcher.dispatch_due_reminders(batch_size=req.batch_size)

    return DispatchResponse(
        processed_count=summary.processed_count,
        delivered_count=summary.delivered_count,
        retried_count=summary.retried_count,
        failed_count=summary.failed_count,
        recovered_count=summary.recovered_count,
        skipped_count=summary.skipped_count,
        details=summary.details,
    )


def _build_reminder_response(r: Reminder) -> ReminderResponse:
    return ReminderResponse(
        id=r.id,
        commitment_id=r.commitment_id,
        due_at=r.due_at,
        channel=r.channel,
        status=r.status,
        attempt_count=r.attempt_count,
        idempotency_key=r.idempotency_key,
        created_at=r.created_at,
        updated_at=r.updated_at,
    )
