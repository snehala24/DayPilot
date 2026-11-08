import uuid
from datetime import timedelta

from app.api.daily_review import get_daily_review
from app.models.database import utc_now
from app.models.entities import (
    Commitment,
    Conflict,
    DeliveryAttempt,
    Plan,
    PlanItem,
    Proposal,
    Reminder,
    User,
)
from app.review.engine import build_daily_review


def test_daily_review_baseline_metrics(db_session, seeded_db):
    user = db_session.query(User).first()
    today = utc_now().date()

    review = build_daily_review(db=db_session, user=user, review_date=today)
    assert review.review_date == today
    assert review.factual_metrics["completed_count"] == 0
    assert review.factual_metrics["scheduled_uncompleted_count"] == 0
    assert review.factual_metrics["conflicts_count"] == 0
    assert review.factual_metrics["pending_proposals_count"] == 0
    assert review.factual_metrics["reminders_needing_attention_count"] == 0
    assert len(review.suggested_actions) >= 1


def test_daily_review_factual_observations(db_session, seeded_db):
    user = db_session.query(User).first()
    now = utc_now()
    today = now.date()

    # 1. Add completed commitment today
    c_done = Commitment(
        id=uuid.uuid4(),
        user_id=user.id,
        title="Completed Quarterly Report",
        status="done",
        priority=2,
        updated_at=now,
    )
    db_session.add(c_done)

    # 2. Add an overdue commitment
    c_overdue = Commitment(
        id=uuid.uuid4(),
        user_id=user.id,
        title="Overdue Tax Return",
        status="open",
        priority=4,
        due_at=now - timedelta(days=2),
    )
    db_session.add(c_overdue)

    # 3. Add an incomplete scheduled commitment in today's plan
    c_scheduled = Commitment(
        id=uuid.uuid4(),
        user_id=user.id,
        title="Client Strategy Sync",
        status="open",
        priority=3,
        due_at=now + timedelta(hours=4),
    )
    db_session.add(c_scheduled)
    db_session.commit()

    plan = Plan(
        id=uuid.uuid4(),
        user_id=user.id,
        plan_date=today,
        status="proposed",
    )
    db_session.add(plan)
    db_session.commit()

    plan_item = PlanItem(
        id=uuid.uuid4(),
        plan_id=plan.id,
        commitment_id=c_scheduled.id,
        starts_at=now + timedelta(hours=1),
        ends_at=now + timedelta(hours=2),
    )
    conflict = Conflict(
        id=uuid.uuid4(),
        plan_id=plan.id,
        commitment_id=c_scheduled.id,
        kind="time_window_exceeded",
        alternatives=[{"option": "Reschedule"}],
    )
    db_session.add_all([plan_item, conflict])

    # 4. Add pending proposal
    prop = Proposal(
        id=uuid.uuid4(),
        user_id=user.id,
        commitment_id=c_scheduled.id,
        kind="calendar_create",
        payload={"title": "Client Strategy Sync"},
        status="pending",
        idempotency_key="review-prop-001",
        expires_at=now + timedelta(hours=24),
    )
    db_session.add(prop)

    # 5. Add reminder needing attention
    rem = Reminder(
        id=uuid.uuid4(),
        commitment_id=c_scheduled.id,
        due_at=now - timedelta(minutes=10),
        status="needs_attention",
        attempt_count=3,
        idempotency_key="review-rem-001",
    )
    db_session.add(rem)
    db_session.commit()

    attempt = DeliveryAttempt(
        id=uuid.uuid4(),
        reminder_id=rem.id,
        outcome="failure",
        error="Simulated permanent 500 error",
        attempted_at=now - timedelta(minutes=5),
    )
    db_session.add(attempt)
    db_session.commit()

    # Execute review build
    review = build_daily_review(db=db_session, user=user, review_date=today)

    assert review.factual_metrics["completed_count"] == 1
    assert review.completed_today[0].title == "Completed Quarterly Report"

    assert review.factual_metrics["overdue_count"] >= 1
    assert any(c.title == "Overdue Tax Return" for c in review.overdue)

    assert review.factual_metrics["scheduled_uncompleted_count"] == 1
    assert review.scheduled_uncompleted[0].title == "Client Strategy Sync"

    assert review.factual_metrics["conflicts_count"] == 1
    assert review.unresolved_conflicts[0].kind == "time_window_exceeded"

    assert review.factual_metrics["pending_proposals_count"] >= 1
    assert review.factual_metrics["reminders_needing_attention_count"] == 1
    assert (
        review.reminders_needing_attention[0].last_error
        == "Simulated permanent 500 error"
    )

    # Verify suggestions generated deterministically
    assert any("pending proposal" in s.lower() for s in review.suggested_actions)
    assert any("failed delivery" in s.lower() for s in review.suggested_actions)
    assert any("past due" in s.lower() for s in review.suggested_actions)


def test_daily_review_api_endpoint(db_session, seeded_db):
    resp = get_daily_review(review_date=None, db=db_session, llm_client=None)
    assert resp.review_date == utc_now().date()
    assert isinstance(resp.factual_metrics, dict)
    assert isinstance(resp.suggested_actions, list)
    assert resp.narrative_summary is not None
