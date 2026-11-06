import uuid

import pytest
from fastapi import HTTPException

from app.agent.client import FakeLLMClient
from app.agent.schemas import (
    ConfirmCommitmentsRequest,
    ConfirmedCommitmentInput,
    ExtractedCommitment,
    RawExtractionResult,
    RawInputRequest,
)
from app.api.commitments import confirm_commitments, get_commitment, list_commitments
from app.api.inputs import submit_raw_input
from app.models.entities import AuditEvent, Commitment, CommitmentDependency, Note


def test_submit_raw_input_creates_note_not_commitments(db_session, seeded_db):
    """Safety Invariant: POST /inputs persists raw note, NEVER creates commitments or triggers external actions."""
    fake_client = FakeLLMClient()
    fake_client.set_canned_response(
        "Buy milk",
        RawExtractionResult(
            commitments=[
                ExtractedCommitment(
                    title="Buy milk",
                    due_date="2026-11-07",
                    priority=3,
                )
            ]
        ),
    )

    req = RawInputRequest(raw_text="Remember to buy milk tomorrow.")
    commitments_before = db_session.query(Commitment).count()
    notes_before = db_session.query(Note).count()

    review = submit_raw_input(payload=req, db=db_session, llm_client=fake_client)

    # Note must be persisted
    notes_after = db_session.query(Note).count()
    assert notes_after == notes_before + 1
    persisted_note = db_session.query(Note).filter(Note.id == review.note_id).first()
    assert persisted_note is not None
    assert persisted_note.raw_text == req.raw_text

    # Review returned correctly
    assert len(review.commitments) == 1
    assert review.commitments[0].title == "Buy milk"

    # CRITICAL: No commitments created in DB
    commitments_after = db_session.query(Commitment).count()
    assert commitments_after == commitments_before


def test_confirm_commitments_workflow(db_session, seeded_db):
    """User reviews and confirms commitments; persists to DB with provenance and audit log."""
    fake_client = FakeLLMClient()
    fake_client.set_canned_response(
        "Deploy app",
        RawExtractionResult(
            commitments=[
                ExtractedCommitment(title="Deploy app", due_date="2026-11-10"),
                ExtractedCommitment(title="Run migration", due_date="2026-11-09"),
            ]
        ),
    )

    # 1. Capture note
    input_req = RawInputRequest(
        raw_text="Deploy app on 2026-11-10 after Run migration on 2026-11-09."
    )
    review = submit_raw_input(payload=input_req, db=db_session, llm_client=fake_client)

    # 2. Confirm both commitments with dependency
    confirm_req = ConfirmCommitmentsRequest(
        note_id=review.note_id,
        commitments=[
            ConfirmedCommitmentInput(
                title="Run migration",
                due_date="2026-11-09",
                due_time="10:00",
                priority=1,
                estimate_minutes=30,
            ),
            ConfirmedCommitmentInput(
                title="Deploy app",
                due_date="2026-11-10",
                due_time="14:00",
                priority=2,
                estimate_minutes=60,
                dependencies=["Run migration"],
            ),
        ],
        idempotency_key="confirm-key-001",
    )

    resp = confirm_commitments(payload=confirm_req, db=db_session)

    assert resp.status == "confirmed"
    assert len(resp.confirmed_commitment_ids) == 2
    assert resp.audit_event_id is not None

    # Verify persisted commitments in DB
    deploy_commit = (
        db_session.query(Commitment).filter(Commitment.title == "Deploy app").first()
    )
    migration_commit = (
        db_session.query(Commitment).filter(Commitment.title == "Run migration").first()
    )

    assert deploy_commit is not None
    assert migration_commit is not None
    assert deploy_commit.source_note_id == review.note_id
    assert deploy_commit.due_at is not None

    # Verify dependency in DB
    dep = (
        db_session.query(CommitmentDependency)
        .filter(
            CommitmentDependency.commitment_id == deploy_commit.id,
            CommitmentDependency.depends_on_id == migration_commit.id,
        )
        .first()
    )
    assert dep is not None

    # Verify append-only AuditEvent
    audit = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.id == resp.audit_event_id)
        .first()
    )
    assert audit is not None
    assert audit.action == "confirm_extraction"
    assert audit.actor == "person"


def test_confirm_commitments_idempotency(db_session, seeded_db):
    """Submitting the same idempotency key returns the existing commitments without duplicates."""
    note = Note(
        id=uuid.uuid4(),
        user_id=seeded_db.query(Commitment).first().user_id,
        raw_text="Meeting with client.",
        captured_at=db_session.query(Commitment).first().created_at,
        created_at=db_session.query(Commitment).first().created_at,
        updated_at=db_session.query(Commitment).first().created_at,
    )
    db_session.add(note)
    db_session.commit()

    confirm_req = ConfirmCommitmentsRequest(
        note_id=note.id,
        commitments=[
            ConfirmedCommitmentInput(title="Meeting with client", priority=2),
        ],
        idempotency_key="idemp-test-duplicate",
    )

    resp1 = confirm_commitments(payload=confirm_req, db=db_session)
    assert resp1.status == "confirmed"

    # Second call with identical key
    resp2 = confirm_commitments(payload=confirm_req, db=db_session)
    assert resp2.status == "idempotent_duplicate"
    assert resp2.confirmed_commitment_ids == resp1.confirmed_commitment_ids


def test_list_and_get_commitments(db_session, seeded_db):
    """Test GET /commitments and GET /commitments/{id}."""
    commitments = list_commitments(status="open", project_id=None, db=db_session)
    assert len(commitments) >= 2

    target_id = commitments[0].id
    detail = get_commitment(commitment_id=target_id, db=db_session)
    assert detail.id == target_id
    assert detail.title == commitments[0].title


def test_circular_dependency_rejected_in_confirmation(db_session, seeded_db):
    """Safety Invariant: Circular dependencies (A -> B -> A) must be rejected with 400."""
    note = Note(
        id=uuid.uuid4(),
        user_id=seeded_db.query(Commitment).first().user_id,
        raw_text="Circular task note.",
        captured_at=db_session.query(Commitment).first().created_at,
        created_at=db_session.query(Commitment).first().created_at,
        updated_at=db_session.query(Commitment).first().created_at,
    )
    db_session.add(note)
    db_session.commit()

    cycle_req = ConfirmCommitmentsRequest(
        note_id=note.id,
        commitments=[
            ConfirmedCommitmentInput(
                title="Task Alpha",
                dependencies=["Task Beta"],
            ),
            ConfirmedCommitmentInput(
                title="Task Beta",
                dependencies=["Task Alpha"],
            ),
        ],
    )

    with pytest.raises(HTTPException) as exc_info:
        confirm_commitments(payload=cycle_req, db=db_session)
    assert exc_info.value.status_code == 400
    assert "circular dependency" in exc_info.value.detail.lower()
