import uuid
from datetime import timedelta

import pytest
from fastapi import HTTPException

from app.api.proposals import (
    ApproveProposalRequest,
    CreateProposalRequest,
    RejectProposalRequest,
    approve_proposal,
    create_proposal,
    get_proposal,
    list_proposals,
    reject_proposal,
)
from app.models.database import utc_now
from app.models.entities import AuditEvent, CalendarEvent, Proposal


def test_create_proposal_success(db_session, seeded_db):
    """Test POST /api/v1/proposals creates a proposal in 'pending' state and records audit."""
    starts = (utc_now() + timedelta(days=1)).replace(
        hour=10, minute=0, second=0, microsecond=0
    )
    ends = starts + timedelta(hours=1)

    payload = {
        "title": "Strategy Sync",
        "starts_at": starts.isoformat(),
        "ends_at": ends.isoformat(),
        "tz": "UTC",
    }
    req = CreateProposalRequest(
        kind="calendar_create",
        payload=payload,
        reason="Scheduled from daily plan",
        idempotency_key="prop-test-001",
    )

    resp = create_proposal(req=req, db=db_session)

    assert resp.id is not None
    assert resp.status == "pending"
    assert resp.kind == "calendar_create"
    assert resp.payload["title"] == "Strategy Sync"
    assert resp.expires_at is not None
    assert resp.approval is None

    # Verify no calendar event was created (Hard rule: creating proposal NEVER executes action)
    cal_event = (
        db_session.query(CalendarEvent)
        .filter(CalendarEvent.title == "Strategy Sync")
        .first()
    )
    assert cal_event is None

    # Verify AuditEvent created
    audit = (
        db_session.query(AuditEvent)
        .filter(
            AuditEvent.entity_type == "proposal",
            AuditEvent.entity_id == resp.id,
            AuditEvent.action == "create_proposal",
        )
        .first()
    )
    assert audit is not None
    assert audit.actor == "agent"


def test_create_proposal_idempotency(db_session, seeded_db):
    """Submitting the same idempotency key returns the existing proposal without duplicates."""
    starts = (utc_now() + timedelta(days=1)).replace(
        hour=14, minute=0, second=0, microsecond=0
    )
    ends = starts + timedelta(minutes=45)

    req = CreateProposalRequest(
        kind="calendar_create",
        payload={
            "title": "Design Review",
            "starts_at": starts.isoformat(),
            "ends_at": ends.isoformat(),
            "tz": "UTC",
        },
        idempotency_key="idemp-prop-duplicate-check",
    )

    resp1 = create_proposal(req=req, db=db_session)
    resp2 = create_proposal(req=req, db=db_session)

    assert resp1.id == resp2.id
    count = (
        db_session.query(Proposal)
        .filter(Proposal.idempotency_key == "idemp-prop-duplicate-check")
        .count()
    )
    assert count == 1


def test_list_and_get_proposals(db_session, seeded_db):
    """Test listing and filtering proposals and fetching proposal by ID."""
    now = utc_now()
    p1 = create_proposal(
        req=CreateProposalRequest(
            kind="calendar_create",
            payload={
                "title": "Task A",
                "starts_at": now.isoformat(),
                "ends_at": (now + timedelta(hours=1)).isoformat(),
            },
            idempotency_key="list-1",
        ),
        db=db_session,
    )
    p2 = create_proposal(
        req=CreateProposalRequest(
            kind="reschedule",
            payload={
                "title": "Task B",
                "starts_at": now.isoformat(),
                "ends_at": (now + timedelta(hours=1)).isoformat(),
            },
            idempotency_key="list-2",
        ),
        db=db_session,
    )

    # List all
    all_proposals = list_proposals(db=db_session)
    assert len(all_proposals) >= 2

    # Filter by kind
    reschedule_proposals = list_proposals(kind="reschedule", db=db_session)
    assert any(p.id == p2.id for p in reschedule_proposals)
    assert not any(p.id == p1.id for p in reschedule_proposals)

    # Get single proposal
    single = get_proposal(proposal_id=p1.id, db=db_session)
    assert single.id == p1.id
    assert single.payload["title"] == "Task A"

    # 404 for non-existent ID
    with pytest.raises(HTTPException) as exc_info:
        get_proposal(proposal_id=uuid.uuid4(), db=db_session)
    assert exc_info.value.status_code == 404


def test_approve_proposal_executes_and_verifies(db_session, seeded_db):
    """Approving a proposal triggers the executor, verifies write, and returns verified status."""
    starts = (utc_now() + timedelta(days=1)).replace(
        hour=11, minute=0, second=0, microsecond=0
    )
    ends = starts + timedelta(hours=1)

    created = create_proposal(
        req=CreateProposalRequest(
            kind="calendar_create",
            payload={
                "title": "Client Presentation",
                "starts_at": starts.isoformat(),
                "ends_at": ends.isoformat(),
                "tz": "UTC",
            },
            idempotency_key="approve-exec-verify-01",
        ),
        db=db_session,
    )

    approve_req = ApproveProposalRequest(reason="Approved by user")
    approved_resp = approve_proposal(
        proposal_id=created.id, req=approve_req, db=db_session
    )

    assert approved_resp.status == "verified"
    assert approved_resp.result is not None
    assert approved_resp.result["title"] == "Client Presentation"
    assert approved_resp.approval is not None
    assert approved_resp.approval.decision == "approved"
    assert approved_resp.approval.decided_by == "person"

    # Verify CalendarEvent actually exists in the database
    cal_event = (
        db_session.query(CalendarEvent)
        .filter(CalendarEvent.title == "Client Presentation")
        .first()
    )
    assert cal_event is not None
    assert cal_event.source == "simulated"
    assert str(cal_event.id) == approved_resp.result["calendar_event_id"]


def test_approve_proposal_with_edited_payload(db_session, seeded_db):
    """User can adjust title or time before approving; executor uses edited_payload."""
    starts = (utc_now() + timedelta(days=1)).replace(
        hour=15, minute=0, second=0, microsecond=0
    )
    ends = starts + timedelta(hours=1)

    created = create_proposal(
        req=CreateProposalRequest(
            kind="calendar_create",
            payload={
                "title": "Original Title",
                "starts_at": starts.isoformat(),
                "ends_at": ends.isoformat(),
                "tz": "UTC",
            },
            idempotency_key="approve-edit-01",
        ),
        db=db_session,
    )

    edited = {
        "title": "Adjusted Title By Person",
        "starts_at": starts.isoformat(),
        "ends_at": ends.isoformat(),
        "tz": "UTC",
    }
    approve_req = ApproveProposalRequest(reason="Renamed title", edited_payload=edited)
    approved_resp = approve_proposal(
        proposal_id=created.id, req=approve_req, db=db_session
    )

    assert approved_resp.status == "verified"
    assert approved_resp.result["title"] == "Adjusted Title By Person"

    cal_event = (
        db_session.query(CalendarEvent)
        .filter(CalendarEvent.title == "Adjusted Title By Person")
        .first()
    )
    assert cal_event is not None


def test_reject_proposal(db_session, seeded_db):
    """Rejecting a proposal marks status 'rejected' and does NOT execute any write."""
    starts = (utc_now() + timedelta(days=1)).replace(
        hour=16, minute=0, second=0, microsecond=0
    )
    ends = starts + timedelta(hours=1)

    created = create_proposal(
        req=CreateProposalRequest(
            kind="calendar_create",
            payload={
                "title": "Unwanted Meeting",
                "starts_at": starts.isoformat(),
                "ends_at": ends.isoformat(),
                "tz": "UTC",
            },
            idempotency_key="reject-01",
        ),
        db=db_session,
    )

    reject_req = RejectProposalRequest(reason="I do not want this meeting")
    rejected_resp = reject_proposal(
        proposal_id=created.id, req=reject_req, db=db_session
    )

    assert rejected_resp.status == "rejected"
    assert rejected_resp.approval is not None
    assert rejected_resp.approval.decision == "rejected"

    # Verify no calendar event was written
    cal_event = (
        db_session.query(CalendarEvent)
        .filter(CalendarEvent.title == "Unwanted Meeting")
        .first()
    )
    assert cal_event is None


def test_cannot_approve_already_decided_proposal(db_session, seeded_db):
    """Cannot approve an already rejected or verified proposal."""
    starts = (utc_now() + timedelta(days=1)).replace(
        hour=17, minute=0, second=0, microsecond=0
    )
    ends = starts + timedelta(hours=1)

    created = create_proposal(
        req=CreateProposalRequest(
            kind="calendar_create",
            payload={
                "title": "Decision Check",
                "starts_at": starts.isoformat(),
                "ends_at": ends.isoformat(),
                "tz": "UTC",
            },
            idempotency_key="decided-check-01",
        ),
        db=db_session,
    )

    reject_proposal(
        proposal_id=created.id,
        req=RejectProposalRequest(reason="Rejected first"),
        db=db_session,
    )

    # Attempt to approve rejected proposal
    with pytest.raises(HTTPException) as exc_info:
        approve_proposal(proposal_id=created.id, db=db_session)
    assert exc_info.value.status_code == 400


def test_cannot_approve_expired_proposal(db_session, seeded_db):
    """An expired proposal cannot be approved."""
    starts = utc_now() + timedelta(hours=1)
    ends = starts + timedelta(hours=1)

    created = create_proposal(
        req=CreateProposalRequest(
            kind="calendar_create",
            payload={
                "title": "Expired Proposal",
                "starts_at": starts.isoformat(),
                "ends_at": ends.isoformat(),
                "tz": "UTC",
            },
            idempotency_key="expired-01",
        ),
        db=db_session,
    )

    # Manually expire the proposal in DB
    p = db_session.query(Proposal).filter(Proposal.id == created.id).first()
    p.expires_at = utc_now() - timedelta(minutes=10)
    db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        approve_proposal(proposal_id=created.id, db=db_session)
    assert exc_info.value.status_code == 400
    assert "expired" in exc_info.value.detail.lower()
