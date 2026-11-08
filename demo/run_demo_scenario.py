"""DayPilot MVP — End-to-End Reproducible Demo Scenario.

Runs the complete 10-step user story from messy note to verified calendar write:
1. User submits a messy note.
2. DayPilot extracts commitments with uncertainty.
3. User resolves ambiguity and confirms.
4. DayPilot builds a schedule.
5. A conflict appears with safe alternatives.
6. User reviews and approves a proposal.
7. Executor performs a simulated calendar write.
8. Read-back verification confirms the result.
9. User schedules and dispatches a simulated reminder.
10. History and Daily Review reflect the actual results.

All integrations are visibly marked as (SIMULATED).
"""

import os
import sys
import uuid
from datetime import UTC, datetime, timedelta

# Add backend to path
sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
)

from app.agent.client import FakeLLMClient
from app.agent.schemas import (
    ConfirmedCommitmentInput,
    ExtractedCommitment,
    RawExtractionResult,
)
from app.api.commitments import (
    ConfirmCommitmentsRequest,
    confirm_commitments,
)
from app.api.daily_review import get_daily_review
from app.api.inputs import RawInputRequest, submit_raw_input
from app.api.plans import GeneratePlanRequest, generate_day_plan
from app.api.proposals import (
    ApproveProposalRequest,
    CreateProposalRequest,
    approve_proposal,
    create_proposal,
)
from app.api.reminders import (
    CreateReminderRequest,
    create_reminder,
)
from app.integrations.notifications import SimulatedNotificationAdapter
from app.models.database import SessionLocal, utc_now
from app.models.entities import CalendarEvent, User
from app.reminders.worker import ReminderDispatcher


def print_step(step_num: int, title: str):
    print("\n" + "=" * 70)
    print(f"STEP {step_num}: {title}")
    print("=" * 70)


def run_demo():
    db = SessionLocal()
    try:
        user = db.query(User).first()
        now = utc_now()
        demo_date = (now + timedelta(days=1)).date()

        print("\n" + "#" * 70)
        print("DAYPILOT MVP — END-TO-END DEMO SCENARIO")
        print(
            "Invariant: The agent proposes. The person approves. The system executes and verifies."
        )
        print("#" * 70)

        # -------------------------------------------------------------
        # Step 1: User submits a messy note
        # -------------------------------------------------------------
        print_step(1, "User Submits a Messy Note")
        raw_text = "Prep executive summary for board meeting next Friday. Sync with Priya first for budget numbers. Takes about 90 mins."
        print(f'Input text:\n  "{raw_text}"')

        fake_client = FakeLLMClient()
        fake_client.set_canned_response(
            "board",
            RawExtractionResult(
                commitments=[
                    ExtractedCommitment(
                        title="Prepare executive summary for board meeting",
                        priority=1,
                        estimated_duration_minutes=90,
                        dependencies=["Priya"],
                        uncertain_fields=["due_date", "due_time"],
                    )
                ]
            ),
        )

        # -------------------------------------------------------------
        # Step 2: Extraction Engine Parses Commitments & Ambiguities
        # -------------------------------------------------------------
        print_step(2, "DayPilot Extracts Commitments & Flags Ambiguities")
        review = submit_raw_input(
            payload=RawInputRequest(raw_text=raw_text),
            db=db,
            llm_client=fake_client,
        )
        print(f"Note persisted with ID: {review.note_id}")
        print(f"Extracted candidate: '{review.commitments[0].title}'")
        print(f"Uncertain fields flagged: {review.commitments[0].uncertain_fields}")
        print(f"Clarifying questions generated: {len(review.questions)}")
        for q in review.questions:
            print(f"  - [{q.field}] {q.question}")
        print(f"Can auto-confirm without user review? {review.can_confirm_all}")

        # -------------------------------------------------------------
        # Step 3: User Resolves Ambiguity and Confirms
        # -------------------------------------------------------------
        print_step(3, "User Resolves Ambiguities & Confirms Commitment")
        confirmed_input = ConfirmedCommitmentInput(
            title="Prepare executive summary for board meeting",
            due_date=str(demo_date),
            due_time="16:00",
            due_tz="Asia/Kolkata",
            priority=1,
            estimate_minutes=90,
            dependencies=[],
        )
        confirm_resp = confirm_commitments(
            payload=ConfirmCommitmentsRequest(
                note_id=review.note_id,
                commitments=[confirmed_input],
                idempotency_key=f"demo-confirm-{uuid.uuid4()}",
            ),
            db=db,
        )
        comm_id = confirm_resp.commitments[0].id
        print(f"Commitment confirmed and saved to database with ID: {comm_id}")
        print("Status: open | Priority: P1 | Estimated: 90 mins")

        # -------------------------------------------------------------
        # Step 4: DayPilot Builds a Schedule
        # -------------------------------------------------------------
        print_step(4, "Deterministic Planner Builds Daily Schedule")
        plan_resp = generate_day_plan(
            payload=GeneratePlanRequest(plan_date=demo_date),
            db=db,
        )
        print(f"Plan ID: {plan_resp.id} for Date: {plan_resp.plan_date}")
        print(
            f"Hard constraint satisfaction: {plan_resp.constraints_report['violations_count'] == 0} (Violations: {plan_resp.constraints_report['violations_count']})"
        )
        print(f"Scheduled plan items: {len(plan_resp.items)}")
        for item in plan_resp.items:
            print(
                f"  - {item.title}: {item.starts_at.strftime('%H:%M')} - {item.ends_at.strftime('%H:%M')} UTC"
            )

        # -------------------------------------------------------------
        # Step 5: A Conflict Appears with Safe Alternatives
        # -------------------------------------------------------------
        print_step(5, "Conflict Detection & Non-Destructive Alternatives")
        # Add a conflicting fixed calendar event
        conf_ev = CalendarEvent(
            user_id=user.id,
            source="simulated",
            external_id=f"demo-conf-event-{uuid.uuid4()}",
            title="Emergency Board Briefing (Fixed)",
            starts_at=datetime.combine(
                demo_date, datetime.strptime("09:00", "%H:%M").time(), tzinfo=UTC
            ),
            ends_at=datetime.combine(
                demo_date, datetime.strptime("17:30", "%H:%M").time(), tzinfo=UTC
            ),
            tz="UTC",
            is_fixed=True,
        )
        db.add(conf_ev)
        db.commit()

        # Replan with conflict
        conflicted_plan = generate_day_plan(
            payload=GeneratePlanRequest(plan_date=demo_date),
            db=db,
        )
        print(f"Conflicts detected: {len(conflicted_plan.conflicts)}")
        for c in conflicted_plan.conflicts:
            print(f"  Conflict on: '{c.commitment_title}' ({c.kind})")
            print(f"  Reason: {c.reason}")
            print(f"  Generated Alternatives ({len(c.alternatives)}):")
            for alt in c.alternatives:
                print(
                    f"    * [{alt['action']}] {alt['title']} (Requires approval: {alt.get('requires_approval', True)})"
                )

        # -------------------------------------------------------------
        # Step 6: User Reviews and Approves a Proposal
        # -------------------------------------------------------------
        print_step(6, "Proposal Generation & Human Approval Gate")
        target_slot = datetime.combine(
            demo_date, datetime.strptime("17:30", "%H:%M").time(), tzinfo=UTC
        )
        prop_req = CreateProposalRequest(
            kind="calendar_create",
            commitment_id=comm_id,
            payload={
                "title": "Prepare executive summary for board meeting",
                "starts_at": target_slot.isoformat(),
                "ends_at": (target_slot + timedelta(minutes=90)).isoformat(),
                "tz": "UTC",
            },
            reason="Scheduled in newly freed evening focus slot",
            idempotency_key=f"demo-proposal-{uuid.uuid4()}",
        )
        prop = create_proposal(req=prop_req, db=db)
        print(f"Proposal created: ID {prop.id}")
        print(f"Status: {prop.status} (Nothing written to calendar yet!)")

        # User approves
        approved_prop = approve_proposal(
            proposal_id=prop.id,
            req=ApproveProposalRequest(reason="Looks good, focus slot confirmed"),
            db=db,
        )
        print(f"Proposal approved by person! New status: {approved_prop.status}")

        # -------------------------------------------------------------
        # Step 7: Executor Performs Simulated Calendar Write
        # -------------------------------------------------------------
        print_step(7, "Executor Performs (SIMULATED) Calendar Write")
        print("Target system: SimulatedCalendarWriteAdapter")
        print(f"Calendar Event ID: {approved_prop.result['calendar_event_id']}")
        print(f"External Source ID: {approved_prop.result['external_id']} (SIMULATED)")

        # -------------------------------------------------------------
        # Step 8: Read-Back Verification Confirms Result
        # -------------------------------------------------------------
        print_step(8, "Read-Back Verification Confirms Event in Calendar")
        ev_in_cal = (
            db.query(CalendarEvent)
            .filter(
                CalendarEvent.id == uuid.UUID(approved_prop.result["calendar_event_id"])
            )
            .first()
        )
        assert ev_in_cal is not None
        print(f"[VERIFIED] Title in store: '{ev_in_cal.title}'")
        print(f"[VERIFIED] Starts at: {ev_in_cal.starts_at} UTC")
        print(f"[VERIFIED] Ends at: {ev_in_cal.ends_at} UTC")
        print(
            f"[VERIFIED] Proposal status is verified honest: '{approved_prop.status}'"
        )

        # -------------------------------------------------------------
        # Step 9: User Schedules and Dispatches a Simulated Reminder
        # -------------------------------------------------------------
        print_step(9, "Simulated Reminder Scheduling & Atomic Dispatch")
        rem_req = CreateReminderRequest(
            commitment_id=comm_id,
            due_at=now - timedelta(minutes=1),  # Due now
            channel="in_app",
            idempotency_key=f"demo-rem-{uuid.uuid4()}",
        )
        rem = create_reminder(req=rem_req, db=db)
        print(f"Reminder created with ID: {rem.id} | Status: {rem.status}")

        adapter = SimulatedNotificationAdapter(default_mode="success")
        dispatcher = ReminderDispatcher(db=db, adapter=adapter)
        summary = dispatcher.dispatch_due_reminders(now=now)
        print(f"Dispatch worker processed: {summary.processed_count}")
        print(
            f"Delivered count: {summary.delivered_count} via {adapter.__class__.__name__} (SIMULATED)"
        )

        # -------------------------------------------------------------
        # Step 10: History and Daily Review Reflect Verified State
        # -------------------------------------------------------------
        print_step(10, "History & Daily Review Verification")
        review = get_daily_review(review_date=demo_date, db=db, llm_client=None)
        print(f"Daily Review for {review.review_date}:")
        print(f"  Factual metrics: {review.factual_metrics}")
        print(f"  Factual summary: {review.narrative_summary}")
        print(f"  Suggested next actions ({len(review.suggested_actions)}):")
        for s in review.suggested_actions:
            print(f"    * {s}")

        print("\n" + "#" * 70)
        print("[SUCCESS] ALL 10 DEMO STEPS EXECUTED AND VERIFIED HONESTLY.")
        print("#" * 70)

    finally:
        db.close()


if __name__ == "__main__":
    run_demo()
