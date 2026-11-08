"""Tests for user isolation and cross-tenant access prevention."""

import uuid
from datetime import timedelta

import pytest
from fastapi import HTTPException

from app.api.audit import list_audit_events
from app.api.commitments import (
    UpdateCommitmentRequest,
    get_commitment,
    list_commitments,
    update_commitment,
)
from app.api.proposals import (
    ApproveProposalRequest,
    approve_proposal,
    get_proposal,
    list_proposals,
)
from app.api.reminders import (
    get_reminder,
    list_reminders,
)
from app.models.database import utc_now
from app.models.entities import (
    AuditEvent,
    Commitment,
    Proposal,
    Reminder,
    User,
)


def test_user_isolation_across_endpoints(db_session, seeded_db):
    """Verify that User A (first user) cannot list, read, update, or approve records belonging to User B."""
    user_a = db_session.query(User).first()
    assert user_a is not None
    now = utc_now()

    # Create User B (different tenant/identity)
    user_b = User(
        id=uuid.uuid4(),
        email="attacker_user_b@external.local",
        timezone="UTC",
    )
    db_session.add(user_b)
    db_session.flush()

    # 1. Create Commitment for User B
    c_b = Commitment(
        id=uuid.uuid4(),
        user_id=user_b.id,
        title="User B Confidential Secret Strategy",
        status="open",
        priority=1,
    )
    db_session.add(c_b)

    # 2. Create Proposal for User B
    p_b = Proposal(
        id=uuid.uuid4(),
        user_id=user_b.id,
        commitment_id=c_b.id,
        kind="calendar_create",
        payload={"title": "User B Secret Meeting"},
        status="pending",
        idempotency_key=f"user-b-prop-{uuid.uuid4()}",
        expires_at=now + timedelta(hours=1),
    )
    db_session.add(p_b)

    # 3. Create Reminder for User B
    r_b = Reminder(
        id=uuid.uuid4(),
        commitment_id=c_b.id,
        due_at=now + timedelta(hours=1),
        channel="in_app",
        status="scheduled",
        idempotency_key=f"user-b-rem-{uuid.uuid4()}",
    )
    db_session.add(r_b)

    # 4. Create AuditEvent for User B
    a_b = AuditEvent(
        id=uuid.uuid4(),
        user_id=user_b.id,
        entity_type="commitment",
        entity_id=c_b.id,
        action="create_commitment",
        actor="person",
        payload={"title": c_b.title},
        created_at=now,
    )
    db_session.add(a_b)
    db_session.commit()

    # =========================================================================
    # Test Isolation for Commitments
    # =========================================================================
    user_a_commitments = list_commitments(db=db_session)
    assert not any(c.id == c_b.id for c in user_a_commitments)

    with pytest.raises(HTTPException) as exc_get_c:
        get_commitment(commitment_id=c_b.id, db=db_session)
    assert exc_get_c.value.status_code == 404

    with pytest.raises(HTTPException) as exc_upd_c:
        update_commitment(
            commitment_id=c_b.id,
            payload=UpdateCommitmentRequest(title="Tampered title by A"),
            db=db_session,
        )
    assert exc_upd_c.value.status_code == 404

    # =========================================================================
    # Test Isolation for Proposals
    # =========================================================================
    user_a_proposals = list_proposals(db=db_session)
    assert not any(p.id == p_b.id for p in user_a_proposals)

    with pytest.raises(HTTPException) as exc_get_p:
        get_proposal(proposal_id=p_b.id, db=db_session)
    assert exc_get_p.value.status_code == 404

    with pytest.raises(HTTPException) as exc_appr_p:
        approve_proposal(
            proposal_id=p_b.id,
            req=ApproveProposalRequest(reason="Unauthorized approval by A"),
            db=db_session,
        )
    assert exc_appr_p.value.status_code == 404

    # =========================================================================
    # Test Isolation for Reminders
    # =========================================================================
    user_a_reminders = list_reminders(db=db_session)
    assert not any(r.id == r_b.id for r in user_a_reminders)

    with pytest.raises(HTTPException) as exc_get_r:
        get_reminder(reminder_id=r_b.id, db=db_session)
    assert exc_get_r.value.status_code == 404

    # =========================================================================
    # Test Isolation for Audit Events
    # =========================================================================
    user_a_audits = list_audit_events(db=db_session)
    assert not any(ev.id == a_b.id for ev in user_a_audits)
