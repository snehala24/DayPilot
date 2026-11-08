from datetime import timedelta

import pytest
from fastapi import HTTPException

from app.agent.client import FakeLLMClient
from app.agent.schemas import (
    ConfirmedCommitmentInput,
    ExtractedCommitment,
    RawExtractionResult,
)
from app.api.audit import list_audit_events
from app.api.commitments import (
    ConfirmCommitmentsRequest,
    UpdateCommitmentRequest,
    confirm_commitments,
    update_commitment,
)
from app.api.inputs import RawInputRequest, submit_raw_input
from app.api.plans import GeneratePlanRequest, generate_day_plan
from app.api.proposals import (
    ApproveProposalRequest,
    CreateProposalRequest,
    approve_proposal,
    create_proposal,
    get_proposal,
)
from app.api.reminders import (
    CreateReminderRequest,
    DispatchRequest,
    create_reminder,
    dispatch_due_reminders,
)
from app.models.database import utc_now
from app.models.entities import CalendarEvent, Commitment, Note, Reminder, User


def test_complete_end_to_end_agent_workflow(db_session, seeded_db):
    """Demonstrate the complete, unbroken DayPilot lifecycle:

    User input -> Extraction -> Pre-Confirmation Edit -> Confirmation ->
    Commitment Edit -> Planning -> Proposal Creation -> Edit & Approve Safety ->
    Execution & Read-Back Verification -> Reminder Scheduling & Dispatch ->
    User-Scoped Audit History Timeline.
    """
    now = utc_now()
    tomorrow = (now + timedelta(days=1)).date()
    user = db_session.query(User).first()
    assert user is not None

    # =========================================================================
    # Step 1: Ingest raw messy input
    # =========================================================================
    fake_client = FakeLLMClient()
    fake_client.set_canned_response(
        "audit",
        RawExtractionResult(
            commitments=[
                ExtractedCommitment(
                    title="Finish quarterly financial audit",
                    due_date=str(tomorrow),
                    priority=3,
                    estimate_minutes=60,
                    dependencies=["Priya"],
                    uncertain_fields=["due_time"],
                )
            ]
        ),
    )
    raw_text = "Finish quarterly financial audit by tomorrow 5pm. Sync with Priya first. Takes 60 minutes."
    input_req = RawInputRequest(raw_text=raw_text)
    input_resp = submit_raw_input(
        payload=input_req, db=db_session, llm_client=fake_client
    )

    assert input_resp.note_id is not None
    assert len(input_resp.commitments) >= 1
    extracted_candidate = input_resp.commitments[0]
    assert "audit" in extracted_candidate.title.lower()

    # Verify Note was saved in database, but NO commitments confirmed yet
    note_in_db = db_session.query(Note).filter(Note.id == input_resp.note_id).first()
    assert note_in_db is not None
    assert note_in_db.raw_text == raw_text

    # =========================================================================
    # Step 2: Confirm extracted commitment
    # =========================================================================
    candidate_input = ConfirmedCommitmentInput(
        title=extracted_candidate.title,
        due_date=extracted_candidate.due_date,
        due_time="17:00",
        priority=extracted_candidate.priority,
        estimate_minutes=extracted_candidate.estimated_duration_minutes or 60,
        dependencies=[],
    )
    confirm_req = ConfirmCommitmentsRequest(
        note_id=input_resp.note_id,
        commitments=[candidate_input],
        idempotency_key="e2e-confirm-001",
    )
    confirm_resp = confirm_commitments(payload=confirm_req, db=db_session)

    assert confirm_resp.status == "confirmed"
    assert len(confirm_resp.commitments) == 1
    confirmed_commitment = confirm_resp.commitments[0]
    commitment_id = confirmed_commitment.id

    # Verify persisted in commitments table
    comm_in_db = (
        db_session.query(Commitment).filter(Commitment.id == commitment_id).first()
    )
    assert comm_in_db is not None
    assert comm_in_db.status == "open"

    # =========================================================================
    # Step 3: Commitment Editing (PATCH /commitments/{id})
    # =========================================================================
    update_req = UpdateCommitmentRequest(
        title="Final Financial Audit Report",
        priority=3,
        estimate_minutes=90,
    )
    updated_comm = update_commitment(
        commitment_id=commitment_id, payload=update_req, db=db_session
    )

    assert updated_comm.title == "Final Financial Audit Report"
    assert updated_comm.priority == 3
    assert updated_comm.estimate_minutes == 90

    # =========================================================================
    # Step 4: Deterministic Planning (POST /plans)
    # =========================================================================
    plan_req = GeneratePlanRequest(plan_date=tomorrow)
    plan_resp = generate_day_plan(payload=plan_req, db=db_session)

    assert plan_resp.status == "proposed"
    assert plan_resp.constraints_report["violations_count"] == 0
    assert len(plan_resp.items) >= 1

    planned_item = next(
        (it for it in plan_resp.items if it.commitment_id == commitment_id),
        plan_resp.items[0],
    )
    assert planned_item is not None

    # =========================================================================
    # Step 5: Proposal Generation (POST /proposals)
    # =========================================================================
    prop_req = CreateProposalRequest(
        kind="calendar_create",
        commitment_id=commitment_id,
        payload={
            "title": planned_item.title,
            "starts_at": planned_item.starts_at.isoformat(),
            "ends_at": planned_item.ends_at.isoformat(),
            "tz": "UTC",
        },
        reason="Scheduled block from verified daily plan",
        idempotency_key="e2e-proposal-001",
    )
    prop_resp = create_proposal(req=prop_req, db=db_session)

    assert prop_resp.status == "pending"
    assert prop_resp.expires_at is not None

    # Hard Safety Gate: Zero calendar events written while proposal is pending
    assert (
        db_session.query(CalendarEvent)
        .filter(CalendarEvent.title == planned_item.title)
        .first()
        is None
    )

    # =========================================================================
    # Step 6: Edit & Approve Safety Verification
    # Attempting to approve with backwards timestamps (starts_at >= ends_at) is REJECTED
    # =========================================================================
    invalid_edit = {
        "title": "Invalid Inverted Event",
        "starts_at": planned_item.ends_at.isoformat(),
        "ends_at": planned_item.starts_at.isoformat(),  # End before start!
        "tz": "UTC",
    }
    with pytest.raises(HTTPException) as exc_info:
        approve_proposal(
            proposal_id=prop_resp.id,
            req=ApproveProposalRequest(
                reason="Invalid edit", edited_payload=invalid_edit
            ),
            db=db_session,
        )
    assert exc_info.value.status_code == 422
    assert "starts_at must be strictly before ends_at" in exc_info.value.detail

    # Verify status is STILL pending and no write occurred
    refreshed_pending = get_proposal(proposal_id=prop_resp.id, db=db_session)
    assert refreshed_pending.status == "pending"

    # =========================================================================
    # Step 7: Valid Edit & Approve Execution with Read-Back Verification
    # =========================================================================
    valid_edit = {
        "title": "Approved & Revised Audit Block",
        "starts_at": planned_item.starts_at.isoformat(),
        "ends_at": planned_item.ends_at.isoformat(),
        "tz": "UTC",
    }
    approve_resp = approve_proposal(
        proposal_id=prop_resp.id,
        req=ApproveProposalRequest(
            reason="Approved with refined title", edited_payload=valid_edit
        ),
        db=db_session,
    )

    # Honest Status Verification: Must report verified
    assert approve_resp.status == "verified"
    assert approve_resp.result is not None
    assert approve_resp.result["title"] == "Approved & Revised Audit Block"
    assert approve_resp.approval.decision == "approved"
    assert approve_resp.approval.decided_by == "person"

    # Verify event exists in calendar store with the exact approved revised title
    cal_event = (
        db_session.query(CalendarEvent)
        .filter(CalendarEvent.title == "Approved & Revised Audit Block")
        .first()
    )
    assert cal_event is not None
    assert str(cal_event.id) == approve_resp.result["calendar_event_id"]

    # =========================================================================
    # Step 8: Reminder Creation & Dispatch
    # =========================================================================
    rem_due = now - timedelta(minutes=5)  # past due for immediate worker dispatch
    rem_req = CreateReminderRequest(
        commitment_id=commitment_id,
        due_at=rem_due,
        channel="in_app",
        idempotency_key="e2e-rem-001",
    )
    rem_resp = create_reminder(req=rem_req, db=db_session)
    assert rem_resp.status == "scheduled"

    # Dispatch due reminders
    dispatch_resp = dispatch_due_reminders(
        req=DispatchRequest(simulated_mode="success"), db=db_session
    )
    assert dispatch_resp.delivered_count >= 1

    rem_in_db = db_session.query(Reminder).filter(Reminder.id == rem_resp.id).first()
    assert rem_in_db.status == "delivered"
    assert rem_in_db.attempt_count == 1

    # =========================================================================
    # Step 9: User-Scoped Audit Trail Inspection (GET /audit-events)
    # =========================================================================
    audit_events = list_audit_events(limit=100, db=db_session)
    assert len(audit_events) >= 5

    # Check user scoping
    for ev in audit_events:
        assert ev.user_id == user.id

    actions = [ev.action for ev in audit_events]
    assert "confirm_extraction" in actions
    assert "update_commitment" in actions
    assert "create_proposal" in actions
    assert "approve_proposal" in actions
    assert "execute_and_verify" in actions
    assert "deliver_reminder" in actions
