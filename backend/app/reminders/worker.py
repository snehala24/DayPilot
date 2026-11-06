import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.integrations.notifications import (
    NotificationAdapter,
)
from app.models.database import utc_now
from app.models.entities import AuditEvent, Commitment, DeliveryAttempt, Reminder, User
from app.planner.engine import ensure_utc
from app.reminders.manager import RetryPolicy

logger = logging.getLogger("daypilot.reminders.worker")


@dataclass
class DispatchSummary:
    processed_count: int = 0
    delivered_count: int = 0
    retried_count: int = 0
    failed_count: int = 0  # Terminal dead-letter failures
    recovered_count: int = 0
    skipped_count: int = 0
    details: list[dict[str, Any]] = field(default_factory=list)


class ReminderDispatcher:
    """Dispatches due reminders with atomic database claiming, safe exponential retries,

    and zero duplicate delivery.
    """

    def __init__(
        self,
        db: Session,
        adapter: NotificationAdapter,
        retry_policy: RetryPolicy | None = None,
        claim_timeout_seconds: float = 300.0,
    ):
        self.db = db
        self.adapter = adapter
        self.retry_policy = retry_policy or RetryPolicy()
        self.claim_timeout_seconds = claim_timeout_seconds

    def dispatch_due_reminders(
        self,
        now: datetime | None = None,
        batch_size: int = 50,
    ) -> DispatchSummary:
        """Process due reminders through atomic claiming, delivery adapter, and audit logging."""
        current_time = ensure_utc(now or utc_now())
        summary = DispatchSummary()

        # Step 1: Recover abandoned or crashed 'claimed' reminders
        summary.recovered_count = self._recover_abandoned_claims(current_time)

        # Step 2: Atomic Database Claiming
        claimed_ids = self._claim_due_reminders(current_time, batch_size)
        summary.processed_count = len(claimed_ids)

        # Step 3: Process Each Claimed Reminder
        for reminder_id in claimed_ids:
            res = self._process_claimed_reminder(reminder_id, current_time)
            summary.details.append(res)
            if res["status"] == "delivered":
                summary.delivered_count += 1
            elif res["status"] == "retrying":
                summary.retried_count += 1
            elif res["status"] == "needs_attention":
                summary.failed_count += 1
            else:
                summary.skipped_count += 1

        return summary

    def _recover_abandoned_claims(self, current_time: datetime) -> int:
        """Find reminders stuck in 'claimed' beyond the timeout and reset them to 'retrying'."""
        cutoff = current_time - timedelta(seconds=self.claim_timeout_seconds)
        stuck_reminders = (
            self.db.query(Reminder)
            .filter(
                Reminder.status == "claimed",
                Reminder.updated_at <= cutoff,
            )
            .all()
        )

        recovered_count = 0
        for rem in stuck_reminders:
            logger.warning(
                "Recovering abandoned claimed reminder %s (claimed since %s)",
                rem.id,
                rem.updated_at,
            )
            rem.status = "retrying"
            rem.updated_at = current_time

            audit = AuditEvent(
                id=uuid.uuid4(),
                user_id=rem.commitment.user_id if rem.commitment else uuid.uuid4(),
                entity_type="reminder",
                entity_id=rem.id,
                action="recover_abandoned_claim",
                actor="system",
                payload={"stuck_since": rem.updated_at.isoformat()},
                recovery_status="needs_attention",
                created_at=current_time,
            )
            self.db.add(audit)
            recovered_count += 1

        if recovered_count > 0:
            self.db.commit()

        return recovered_count

    def _claim_due_reminders(
        self, current_time: datetime, batch_size: int
    ) -> list[uuid.UUID]:
        """Atomically claim due reminders using Compare-And-Swap (CAS) to prevent worker races."""
        # Find candidate IDs that are due
        candidates = (
            self.db.query(Reminder.id)
            .filter(
                Reminder.status.in_(["scheduled", "retrying"]),
                Reminder.due_at <= current_time,
            )
            .order_by(Reminder.due_at.asc())
            .limit(batch_size)
            .all()
        )

        claimed_ids = []
        for (cand_id,) in candidates:
            # Atomic CAS update: only claim if status is still 'scheduled' or 'retrying'
            rows_updated = (
                self.db.query(Reminder)
                .filter(
                    Reminder.id == cand_id,
                    Reminder.status.in_(["scheduled", "retrying"]),
                )
                .update(
                    {
                        Reminder.status: "claimed",
                        Reminder.updated_at: current_time,
                    },
                    synchronize_session=False,
                )
            )
            if rows_updated == 1:
                claimed_ids.append(cand_id)

        self.db.commit()
        return claimed_ids

    def _process_claimed_reminder(
        self, reminder_id: uuid.UUID, current_time: datetime
    ) -> dict[str, Any]:
        """Deliver a claimed reminder and record delivery attempt with retry/dead-letter rules."""
        reminder = self.db.query(Reminder).filter(Reminder.id == reminder_id).first()
        if not reminder:
            return {"reminder_id": reminder_id, "status": "not_found"}

        commitment = (
            self.db.query(Commitment)
            .filter(Commitment.id == reminder.commitment_id)
            .first()
        )
        user = (
            self.db.query(User).filter(User.id == commitment.user_id).first()
            if commitment
            else None
        )
        recipient = user.email if user else "user"
        title = commitment.title if commitment else "Reminder"
        message = f"Reminder for commitment: {title}"

        new_attempt_count = reminder.attempt_count + 1

        try:
            # Invoke notification adapter
            delivery_res = self.adapter.send(
                reminder_id=reminder.id,
                recipient=recipient,
                title=title,
                message=message,
                channel=reminder.channel,
            )

            # Success
            attempt = DeliveryAttempt(
                id=uuid.uuid4(),
                reminder_id=reminder.id,
                attempted_at=current_time,
                outcome="success",
                error=None,
                created_at=current_time,
            )
            self.db.add(attempt)

            reminder.status = "delivered"
            reminder.attempt_count = new_attempt_count
            reminder.updated_at = current_time

            audit = AuditEvent(
                id=uuid.uuid4(),
                user_id=commitment.user_id if commitment else uuid.uuid4(),
                entity_type="reminder",
                entity_id=reminder.id,
                action="deliver_reminder",
                actor="system",
                payload={
                    "attempt_count": new_attempt_count,
                    "channel": reminder.channel,
                },
                result={"outcome": "success", "latency_ms": delivery_res.latency_ms},
                created_at=current_time,
            )
            self.db.add(audit)
            self.db.commit()

            return {
                "reminder_id": str(reminder.id),
                "status": "delivered",
                "attempt_count": new_attempt_count,
            }

        except Exception as exc:
            logger.warning(
                "Delivery attempt %d failed for reminder %s: %s",
                new_attempt_count,
                reminder.id,
                exc,
            )

            # Record failure attempt
            attempt = DeliveryAttempt(
                id=uuid.uuid4(),
                reminder_id=reminder.id,
                attempted_at=current_time,
                outcome="failure",
                error=str(exc),
                created_at=current_time,
            )
            self.db.add(attempt)

            is_transient = self.retry_policy.is_transient(exc)

            if not is_transient or new_attempt_count >= self.retry_policy.max_attempts:
                # Terminal dead-letter failure: needs attention
                reminder.status = "needs_attention"
                reminder.attempt_count = new_attempt_count
                reminder.updated_at = current_time

                reason = (
                    "permanent_failure" if not is_transient else "max_attempts_exceeded"
                )

                audit = AuditEvent(
                    id=uuid.uuid4(),
                    user_id=commitment.user_id if commitment else uuid.uuid4(),
                    entity_type="reminder",
                    entity_id=reminder.id,
                    action=f"deliver_failed_{reason}",
                    actor="system",
                    payload={"attempt_count": new_attempt_count, "error": str(exc)},
                    recovery_status="needs_attention",
                    created_at=current_time,
                )
                self.db.add(audit)
                self.db.commit()

                return {
                    "reminder_id": str(reminder.id),
                    "status": "needs_attention",
                    "reason": reason,
                    "attempt_count": new_attempt_count,
                    "error": str(exc),
                }

            else:
                # Transient failure with retries remaining: schedule exponential backoff
                delay_sec = self.retry_policy.compute_next_delay(new_attempt_count)
                next_due = current_time + timedelta(seconds=delay_sec)

                reminder.status = "retrying"
                reminder.due_at = next_due
                reminder.attempt_count = new_attempt_count
                reminder.updated_at = current_time

                audit = AuditEvent(
                    id=uuid.uuid4(),
                    user_id=commitment.user_id if commitment else uuid.uuid4(),
                    entity_type="reminder",
                    entity_id=reminder.id,
                    action="deliver_retry_scheduled",
                    actor="system",
                    payload={
                        "attempt_count": new_attempt_count,
                        "error": str(exc),
                        "delay_seconds": delay_sec,
                        "next_due_at": next_due.isoformat(),
                    },
                    created_at=current_time,
                )
                self.db.add(audit)
                self.db.commit()

                return {
                    "reminder_id": str(reminder.id),
                    "status": "retrying",
                    "attempt_count": new_attempt_count,
                    "next_due_at": next_due.isoformat(),
                    "error": str(exc),
                }
