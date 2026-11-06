from datetime import timedelta

import pytest
from fastapi import HTTPException

from app.api.reminders import (
    CreateReminderRequest,
    DispatchRequest,
    cancel_reminder,
    create_reminder,
    dispatch_due_reminders,
    get_reminder,
    list_reminders,
)
from app.models.database import utc_now
from app.models.entities import Commitment, Reminder


def test_create_reminder_api(db_session, seeded_db):
    """Test POST /api/v1/reminders creates a scheduled reminder with attempt_count=0."""
    commitment = db_session.query(Commitment).first()
    assert commitment is not None

    due = utc_now() + timedelta(hours=2)
    req = CreateReminderRequest(
        commitment_id=commitment.id,
        due_at=due,
        channel="in_app",
        idempotency_key="rem-api-test-01",
    )

    resp = create_reminder(req=req, db=db_session)

    assert resp.id is not None
    assert resp.commitment_id == commitment.id
    assert resp.status == "scheduled"
    assert resp.attempt_count == 0
    assert resp.idempotency_key == "rem-api-test-01"


def test_create_reminder_idempotency_api(db_session, seeded_db):
    """Submitting the same idempotency key returns the existing reminder without duplicates."""
    commitment = db_session.query(Commitment).first()
    due = utc_now() + timedelta(hours=3)
    req = CreateReminderRequest(
        commitment_id=commitment.id,
        due_at=due,
        idempotency_key="rem-duplicate-key-check",
    )

    resp1 = create_reminder(req=req, db=db_session)
    resp2 = create_reminder(req=req, db=db_session)

    assert resp1.id == resp2.id
    count = (
        db_session.query(Reminder)
        .filter(Reminder.idempotency_key == "rem-duplicate-key-check")
        .count()
    )
    assert count == 1


def test_list_and_get_reminder_api(db_session, seeded_db):
    """Test listing reminders and getting detailed reminder with attempts."""
    commitment = db_session.query(Commitment).first()
    now = utc_now()

    r1 = create_reminder(
        req=CreateReminderRequest(
            commitment_id=commitment.id,
            due_at=now + timedelta(hours=1),
            idempotency_key="list-rem-1",
        ),
        db=db_session,
    )

    # List
    all_reminders = list_reminders(db=db_session)
    assert len(all_reminders) >= 1
    assert any(r.id == r1.id for r in all_reminders)

    # Filter by status
    scheduled = list_reminders(status="scheduled", db=db_session)
    assert any(r.id == r1.id for r in scheduled)

    # Filter by commitment
    comm_list = list_reminders(commitment_id=commitment.id, db=db_session)
    assert any(r.id == r1.id for r in comm_list)

    # Get details
    detail = get_reminder(reminder_id=r1.id, db=db_session)
    assert detail.id == r1.id
    assert detail.delivery_attempts == []


def test_cancel_reminder_api(db_session, seeded_db):
    """Cancelling a reminder sets status to cancelled; cannot cancel delivered reminder."""
    commitment = db_session.query(Commitment).first()
    r = create_reminder(
        req=CreateReminderRequest(
            commitment_id=commitment.id,
            due_at=utc_now() + timedelta(hours=5),
            idempotency_key="cancel-rem-1",
        ),
        db=db_session,
    )

    cancelled = cancel_reminder(reminder_id=r.id, db=db_session)
    assert cancelled.status == "cancelled"

    # Cannot cancel if marked delivered
    rem_in_db = db_session.query(Reminder).filter(Reminder.id == r.id).first()
    rem_in_db.status = "delivered"
    db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        cancel_reminder(reminder_id=r.id, db=db_session)
    assert exc_info.value.status_code == 400


def test_dispatch_endpoint_api(db_session, seeded_db):
    """Test POST /api/v1/reminders/dispatch controlled worker entry point."""
    commitment = db_session.query(Commitment).first()
    past_due = utc_now() - timedelta(minutes=5)
    r = create_reminder(
        req=CreateReminderRequest(
            commitment_id=commitment.id,
            due_at=past_due,
            idempotency_key="dispatch-api-01",
        ),
        db=db_session,
    )

    dispatch_req = DispatchRequest(simulated_mode="success")
    resp = dispatch_due_reminders(req=dispatch_req, db=db_session)

    assert resp.processed_count >= 1
    assert resp.delivered_count >= 1

    # Verify reminder is delivered in database
    refreshed = db_session.query(Reminder).filter(Reminder.id == r.id).first()
    assert refreshed.status == "delivered"
    assert refreshed.attempt_count == 1
