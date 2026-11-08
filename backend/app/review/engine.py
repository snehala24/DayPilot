"""Deterministic daily review engine.

Constructs factual daily progress and status summaries from persisted DayPilot entities.
Distinguishes facts from suggestions; never invents completion states or productivity scores.
"""

import logging
from datetime import UTC, date, datetime, time

from sqlalchemy.orm import Session

from app.agent.client import LLMClient
from app.models.database import utc_now
from app.models.entities import (
    Commitment,
    DeliveryAttempt,
    Plan,
    Proposal,
    Reminder,
    User,
)
from app.review.schemas import (
    CommitmentReviewItem,
    ConflictReviewItem,
    DailyReviewResponse,
    ProposalReviewItem,
    ReminderAttentionItem,
)

logger = logging.getLogger("daypilot.review.engine")


def build_daily_review(
    db: Session,
    user: User,
    review_date: date,
    llm_client: LLMClient | None = None,
) -> DailyReviewResponse:
    """Build a deterministic daily review for the specified user and date.

    Factual observations are computed strictly from database records.
    Suggestions are deterministically generated from observed gaps or issues.
    """
    user_tz = user.timezone or "UTC"
    now = utc_now()

    # Boundaries for review_date in UTC
    start_dt = datetime.combine(review_date, time.min, tzinfo=UTC)
    end_dt = datetime.combine(review_date, time.max, tzinfo=UTC)

    # 1. Commitments completed on or before target date
    completed_records = (
        db.query(Commitment)
        .filter(
            Commitment.user_id == user.id,
            Commitment.status == "done",
            Commitment.updated_at >= start_dt,
            Commitment.updated_at <= end_dt,
        )
        .all()
    )

    completed_today = [
        CommitmentReviewItem(
            id=c.id,
            title=c.title,
            priority=c.priority,
            status=c.status,
            due_at=c.due_at,
            estimate_minutes=c.estimate_minutes,
        )
        for c in completed_records
    ]

    # 2. Scheduled commitments for review_date that are NOT done
    plan = (
        db.query(Plan)
        .filter(
            Plan.user_id == user.id,
            Plan.plan_date == review_date,
            Plan.status.in_(["proposed", "accepted"]),
        )
        .order_by(Plan.created_at.desc())
        .first()
    )

    scheduled_uncompleted = []
    if plan:
        for item in plan.items:
            comm = item.commitment
            if comm and comm.status != "done":
                scheduled_uncompleted.append(
                    CommitmentReviewItem(
                        id=comm.id,
                        title=comm.title,
                        priority=comm.priority,
                        status=comm.status,
                        due_at=comm.due_at,
                        estimate_minutes=comm.estimate_minutes,
                    )
                )

    # 3. Overdue commitments: open/scheduled/in_progress with due_at < threshold (now or end_dt)
    threshold = min(now, end_dt)
    overdue_records = (
        db.query(Commitment)
        .filter(
            Commitment.user_id == user.id,
            Commitment.status.in_(["open", "scheduled", "in_progress"]),
            Commitment.due_at.isnot(None),
            Commitment.due_at < threshold,
        )
        .all()
    )

    overdue = [
        CommitmentReviewItem(
            id=c.id,
            title=c.title,
            priority=c.priority,
            status=c.status,
            due_at=c.due_at,
            estimate_minutes=c.estimate_minutes,
        )
        for c in overdue_records
    ]

    # 4. Unresolved conflicts from latest plan
    unresolved_conflicts = []
    if plan:
        for conf in plan.conflicts:
            if conf.resolved_by_proposal_id is None:
                comm_title = conf.commitment.title if conf.commitment else "Unknown"
                unresolved_conflicts.append(
                    ConflictReviewItem(
                        id=conf.id,
                        commitment_id=conf.commitment_id,
                        commitment_title=comm_title,
                        kind=conf.kind,
                        reason=getattr(conf, "reason", None),
                        alternatives_count=(
                            len(conf.alternatives) if conf.alternatives else 0
                        ),
                    )
                )

    # 5. Pending proposals awaiting human review (not expired)
    pending_props = (
        db.query(Proposal)
        .filter(
            Proposal.user_id == user.id,
            Proposal.status == "pending",
            Proposal.expires_at > now,
        )
        .all()
    )

    pending_proposals = [
        ProposalReviewItem(
            id=p.id,
            title=(
                p.payload.get("title", f"Proposal for {p.kind}")
                if isinstance(p.payload, dict)
                else p.kind
            ),
            kind=p.kind,
            status=p.status,
            expires_at=p.expires_at,
        )
        for p in pending_props
    ]

    # 6. Reminder delivery failures requiring human attention
    reminder_records = (
        db.query(Reminder)
        .join(Commitment, Reminder.commitment_id == Commitment.id)
        .filter(
            Commitment.user_id == user.id,
            Reminder.status == "needs_attention",
        )
        .all()
    )

    reminders_needing_attention = []
    for r in reminder_records:
        last_attempt = (
            db.query(DeliveryAttempt)
            .filter(DeliveryAttempt.reminder_id == r.id)
            .order_by(DeliveryAttempt.attempted_at.desc())
            .first()
        )
        last_err = last_attempt.error if last_attempt else None
        reminders_needing_attention.append(
            ReminderAttentionItem(
                id=r.id,
                commitment_id=r.commitment_id,
                commitment_title=r.commitment.title if r.commitment else None,
                status=r.status,
                attempt_count=r.attempt_count,
                due_at=r.due_at,
                last_error=last_err,
            )
        )

    # Factual metrics
    factual_metrics = {
        "completed_count": len(completed_today),
        "scheduled_uncompleted_count": len(scheduled_uncompleted),
        "overdue_count": len(overdue),
        "conflicts_count": len(unresolved_conflicts),
        "pending_proposals_count": len(pending_proposals),
        "reminders_needing_attention_count": len(reminders_needing_attention),
    }

    # Deterministic suggestions
    suggested_actions = []
    if factual_metrics["pending_proposals_count"] > 0:
        suggested_actions.append(
            f"Review and decide on {factual_metrics['pending_proposals_count']} pending proposal(s) before they expire."
        )
    if factual_metrics["reminders_needing_attention_count"] > 0:
        suggested_actions.append(
            f"{factual_metrics['reminders_needing_attention_count']} reminder(s) failed delivery and require manual rescheduling or attention."
        )
    if factual_metrics["overdue_count"] > 0:
        suggested_actions.append(
            f"{factual_metrics['overdue_count']} commitment(s) are past due; consider rescheduling deadlines or updating status."
        )
    if factual_metrics["conflicts_count"] > 0:
        suggested_actions.append(
            f"{factual_metrics['conflicts_count']} scheduling conflict(s) exist; inspect proposed alternatives to resolve."
        )
    if factual_metrics["scheduled_uncompleted_count"] > 0:
        suggested_actions.append(
            f"{factual_metrics['scheduled_uncompleted_count']} planned commitment(s) scheduled for today remain in progress."
        )
    if not suggested_actions:
        suggested_actions.append(
            "All planned commitments are on track. No immediate actions required."
        )

    # Narrative summary (deterministic base)
    narrative_summary = (
        f"Review for {review_date}: {factual_metrics['completed_count']} completed, "
        f"{factual_metrics['scheduled_uncompleted_count']} remaining, "
        f"{factual_metrics['overdue_count']} overdue, "
        f"{factual_metrics['pending_proposals_count']} proposals pending review."
    )

    return DailyReviewResponse(
        review_date=review_date,
        timezone=user_tz,
        factual_metrics=factual_metrics,
        completed_today=completed_today,
        scheduled_uncompleted=scheduled_uncompleted,
        overdue=overdue,
        unresolved_conflicts=unresolved_conflicts,
        pending_proposals=pending_proposals,
        reminders_needing_attention=reminders_needing_attention,
        suggested_actions=suggested_actions,
        narrative_summary=narrative_summary,
    )
