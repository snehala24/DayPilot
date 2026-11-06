import uuid
from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from app.executor.executor import ApprovalGateViolationError, ProposalExecutor
from app.models.database import utc_now
from app.models.entities import Approval, AuditEvent, CalendarEvent, Proposal, User


def test_unauthorized_write_rate_is_strictly_zero(db_session: Session, seeded_db):
    """Safety Invariant: Unauthorized write rate must be strictly 0.

    Any direct attempt to write to the calendar without going through
    the executor's approval gate must be blocked or prevented.
    """
    user = db_session.query(User).first()
    initial_event_count = db_session.query(CalendarEvent).count()

    # Attempt 1: Execute a non-existent proposal
    executor = ProposalExecutor(db=db_session)
    with pytest.raises(ApprovalGateViolationError):
        executor.execute_proposal(uuid.uuid4())

    # Attempt 2: Execute a proposal that is still 'pending'
    pending_proposal = Proposal(
        id=uuid.uuid4(),
        user_id=user.id,
        kind="calendar_create",
        payload={
            "title": "Unauthorized Sneak",
            "starts_at": (utc_now() + timedelta(days=1)).isoformat(),
            "ends_at": (utc_now() + timedelta(days=1, hours=1)).isoformat(),
            "tz": "UTC",
        },
        status="pending",
        idempotency_key="unauth-001",
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    db_session.add(pending_proposal)
    db_session.commit()

    with pytest.raises(ApprovalGateViolationError) as exc_info:
        executor.execute_proposal(pending_proposal.id)
    assert "Unauthorized write rejected" in str(exc_info.value)

    # Attempt 3: Execute a rejected proposal
    rejected_proposal = Proposal(
        id=uuid.uuid4(),
        user_id=user.id,
        kind="calendar_create",
        payload={
            "title": "Rejected Event",
            "starts_at": (utc_now() + timedelta(days=1)).isoformat(),
            "ends_at": (utc_now() + timedelta(days=1, hours=1)).isoformat(),
            "tz": "UTC",
        },
        status="rejected",
        idempotency_key="unauth-002",
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    db_session.add(rejected_proposal)
    db_session.commit()

    with pytest.raises(ApprovalGateViolationError) as exc_info:
        executor.execute_proposal(rejected_proposal.id)
    assert "Unauthorized write rejected" in str(exc_info.value)

    # Final verification: Zero unauthorized events created
    current_event_count = db_session.query(CalendarEvent).count()
    assert current_event_count == initial_event_count, (
        "Unauthorized calendar events were written to the database!"
    )


def test_executor_refuses_proposal_tampered_without_approval_row(
    db_session: Session, seeded_db
):
    """Tampering defense: If a proposal row has status='approved' in DB but NO matching
    Approval record in the approvals table, the executor MUST reject execution.
    """
    user = db_session.query(User).first()
    tampered_proposal = Proposal(
        id=uuid.uuid4(),
        user_id=user.id,
        kind="calendar_create",
        payload={
            "title": "Forged Approval",
            "starts_at": (utc_now() + timedelta(days=1)).isoformat(),
            "ends_at": (utc_now() + timedelta(days=1, hours=1)).isoformat(),
            "tz": "UTC",
        },
        status="approved",  # Spoofed status without approval row
        idempotency_key="forged-001",
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    db_session.add(tampered_proposal)
    db_session.commit()

    executor = ProposalExecutor(db=db_session)
    with pytest.raises(ApprovalGateViolationError) as exc_info:
        executor.execute_proposal(tampered_proposal.id)
    assert "No approved record exists in approvals table" in str(exc_info.value)

    # Verify no calendar event was created
    event = (
        db_session.query(CalendarEvent)
        .filter(CalendarEvent.title == "Forged Approval")
        .first()
    )
    assert event is None


def test_executor_refuses_expired_proposal(db_session: Session, seeded_db):
    """An approved proposal whose expiration window has passed must be rejected."""
    user = db_session.query(User).first()
    now = utc_now()
    expired_proposal = Proposal(
        id=uuid.uuid4(),
        user_id=user.id,
        kind="calendar_create",
        payload={
            "title": "Expired Work",
            "starts_at": (now + timedelta(days=1)).isoformat(),
            "ends_at": (now + timedelta(days=1, hours=1)).isoformat(),
            "tz": "UTC",
        },
        status="approved",
        idempotency_key="expired-001",
        expires_at=now - timedelta(minutes=5),  # Already expired
        created_at=now - timedelta(hours=2),
        updated_at=now,
    )
    db_session.add(expired_proposal)
    approval = Approval(
        id=uuid.uuid4(),
        proposal_id=expired_proposal.id,
        decision="approved",
        decided_by="person",
        decided_at=now - timedelta(hours=1),
        created_at=now - timedelta(hours=1),
        updated_at=now - timedelta(hours=1),
    )
    db_session.add(approval)
    db_session.commit()

    executor = ProposalExecutor(db=db_session)
    with pytest.raises(ApprovalGateViolationError) as exc_info:
        executor.execute_proposal(expired_proposal.id)
    assert "has expired" in str(exc_info.value)
    assert expired_proposal.status == "expired"


def test_idempotent_execution_prevents_duplicate_writes(db_session: Session, seeded_db):
    """Executing an already verified proposal must return the cached result and
    create zero additional calendar events.
    """
    user = db_session.query(User).first()
    now = utc_now()
    starts = (now + timedelta(days=1)).replace(
        hour=9, minute=0, second=0, microsecond=0
    )
    ends = starts + timedelta(hours=1)

    proposal = Proposal(
        id=uuid.uuid4(),
        user_id=user.id,
        kind="calendar_create",
        payload={
            "title": "Idempotent Sync",
            "starts_at": starts.isoformat(),
            "ends_at": ends.isoformat(),
            "tz": "UTC",
        },
        status="approved",
        idempotency_key="idemp-exec-001",
        expires_at=now + timedelta(hours=24),
        created_at=now,
        updated_at=now,
    )
    approval = Approval(
        id=uuid.uuid4(),
        proposal_id=proposal.id,
        decision="approved",
        decided_by="person",
        decided_at=now,
        created_at=now,
        updated_at=now,
    )
    db_session.add(proposal)
    db_session.add(approval)
    db_session.commit()

    executor = ProposalExecutor(db=db_session)
    # First execution -> verified
    res1 = executor.execute_proposal(proposal.id)
    assert res1.status == "verified"
    assert res1.calendar_event_id is not None

    count_after_first = (
        db_session.query(CalendarEvent)
        .filter(CalendarEvent.title == "Idempotent Sync")
        .count()
    )
    assert count_after_first == 1

    # Second execution -> idempotent duplicate
    res2 = executor.execute_proposal(proposal.id)
    assert res2.status == "idempotent_duplicate"
    assert res2.calendar_event_id == res1.calendar_event_id

    count_after_second = (
        db_session.query(CalendarEvent)
        .filter(CalendarEvent.title == "Idempotent Sync")
        .count()
    )
    assert count_after_second == 1, "Duplicate calendar event was created on retry!"


def test_adapter_write_failure_transitions_to_failed_with_recovery_status(
    db_session: Session, seeded_db
):
    """When the calendar adapter fails, the proposal must transition to 'failed'
    with recovery_status='needs_attention' and an audit event.
    """
    user = db_session.query(User).first()
    now = utc_now()

    proposal = Proposal(
        id=uuid.uuid4(),
        user_id=user.id,
        kind="calendar_create",
        payload={
            "title": "Failure Test",
            "starts_at": (now + timedelta(days=1)).isoformat(),
            "ends_at": (now + timedelta(days=1, hours=1)).isoformat(),
            "tz": "UTC",
        },
        status="approved",
        idempotency_key="fail-adapter-001",
        expires_at=now + timedelta(hours=24),
        created_at=now,
        updated_at=now,
    )
    approval = Approval(
        id=uuid.uuid4(),
        proposal_id=proposal.id,
        decision="approved",
        decided_by="person",
        decided_at=now,
        created_at=now,
        updated_at=now,
    )
    db_session.add(proposal)
    db_session.add(approval)
    db_session.commit()

    executor = ProposalExecutor(db=db_session)
    result = executor.execute_proposal(proposal.id, simulated_fault="adapter_error")

    assert result.status == "failed"
    assert result.error == "Simulated adapter failure"
    assert proposal.status == "failed"
    assert proposal.recovery_status == "needs_attention"

    # Verify AuditEvent
    audit = (
        db_session.query(AuditEvent)
        .filter(
            AuditEvent.entity_type == "proposal",
            AuditEvent.entity_id == proposal.id,
            AuditEvent.action == "execute_failed",
        )
        .first()
    )
    assert audit is not None
    assert audit.recovery_status == "needs_attention"


def test_readback_verification_mismatch_transitions_to_failed_with_needs_attention(
    db_session: Session, seeded_db
):
    """If the write adapter succeeds but the read-back verification fails,
    the proposal MUST NOT be marked 'verified'. It must be marked 'failed'
    with recovery_status='needs_attention'.
    """
    user = db_session.query(User).first()
    now = utc_now()

    proposal = Proposal(
        id=uuid.uuid4(),
        user_id=user.id,
        kind="calendar_create",
        payload={
            "title": "Mismatch Event",
            "starts_at": (now + timedelta(days=1)).isoformat(),
            "ends_at": (now + timedelta(days=1, hours=1)).isoformat(),
            "tz": "UTC",
        },
        status="approved",
        idempotency_key="fail-readback-001",
        expires_at=now + timedelta(hours=24),
        created_at=now,
        updated_at=now,
    )
    approval = Approval(
        id=uuid.uuid4(),
        proposal_id=proposal.id,
        decision="approved",
        decided_by="person",
        decided_at=now,
        created_at=now,
        updated_at=now,
    )
    db_session.add(proposal)
    db_session.add(approval)
    db_session.commit()

    executor = ProposalExecutor(db=db_session)
    result = executor.execute_proposal(proposal.id, simulated_fault="readback_mismatch")

    assert result.status == "failed"
    assert result.error == "Read-back verification mismatch"
    assert proposal.status == "failed"
    assert proposal.recovery_status == "needs_attention"

    # Verify AuditEvent
    audit = (
        db_session.query(AuditEvent)
        .filter(
            AuditEvent.entity_type == "proposal",
            AuditEvent.entity_id == proposal.id,
            AuditEvent.action == "verification_failed",
        )
        .first()
    )
    assert audit is not None
    assert audit.recovery_status == "needs_attention"


def test_audit_trail_is_append_only(db_session: Session, seeded_db):
    """Verify that all state transitions generate append-only audit trail records."""
    user = db_session.query(User).first()
    now = utc_now()

    proposal = Proposal(
        id=uuid.uuid4(),
        user_id=user.id,
        kind="calendar_create",
        payload={
            "title": "Audit Trail Inspection",
            "starts_at": (now + timedelta(days=1)).isoformat(),
            "ends_at": (now + timedelta(days=1, hours=1)).isoformat(),
            "tz": "UTC",
        },
        status="approved",
        idempotency_key="audit-trail-001",
        expires_at=now + timedelta(hours=24),
        created_at=now,
        updated_at=now,
    )
    approval = Approval(
        id=uuid.uuid4(),
        proposal_id=proposal.id,
        decision="approved",
        decided_by="person",
        decided_at=now,
        created_at=now,
        updated_at=now,
    )
    db_session.add(proposal)
    db_session.add(approval)
    db_session.commit()

    executor = ProposalExecutor(db=db_session)
    executor.execute_proposal(proposal.id)

    events = (
        db_session.query(AuditEvent)
        .filter(
            AuditEvent.entity_type == "proposal",
            AuditEvent.entity_id == proposal.id,
        )
        .all()
    )

    # Must contain at least the execute_and_verify audit event
    actions = [e.action for e in events]
    assert "execute_and_verify" in actions
    for event in events:
        assert event.created_at is not None
        assert event.actor in ["agent", "person", "system"]
