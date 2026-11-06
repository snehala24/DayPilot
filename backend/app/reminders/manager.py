import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.integrations.notifications import (
    PermanentDeliveryError,
    TransientDeliveryError,
)
from app.models.database import utc_now
from app.models.entities import AuditEvent, Commitment, Reminder, User
from app.planner.engine import ensure_utc


class ReminderError(Exception):
    """Base exception for reminder management operations."""


class ReminderNotFoundError(ReminderError):
    pass


class ReminderStateError(ReminderError):
    pass


@dataclass
class RetryPolicy:
    """Configurable exponential backoff retry policy for reminder dispatch."""

    initial_delay_seconds: float = 60.0
    max_delay_seconds: float = 3600.0
    backoff_factor: float = 2.0
    max_attempts: int = 3

    def compute_next_delay(self, attempt_count: int) -> float:
        """Compute exponential backoff delay in seconds for the given attempt count."""
        if attempt_count <= 1:
            delay = self.initial_delay_seconds
        else:
            delay = self.initial_delay_seconds * (
                self.backoff_factor ** (attempt_count - 1)
            )
        return min(delay, self.max_delay_seconds)

    def is_transient(self, exc: Exception) -> bool:
        """Determine whether an error is transient (retryable) or permanent."""
        if isinstance(exc, PermanentDeliveryError):
            return False
        if isinstance(exc, TransientDeliveryError):
            return True
        # Default unrecognized exceptions to transient unless permanent
        return True


class ReminderManager:
    """Manages reminder lifecycle, scheduling, state tracking, and cancellation."""

    def __init__(self, db: Session):
        self.db = db

    def create_reminder(
        self,
        commitment_id: uuid.UUID,
        due_at: datetime,
        channel: str = "in_app",
        idempotency_key: str | None = None,
        user_id: uuid.UUID | None = None,
    ) -> Reminder:
        """Create a scheduled reminder for a commitment.

        Enforces:
        - Commitment exists and belongs to user.
        - Idempotency key uniqueness (returns existing reminder if key exists).
        - Offset-aware UTC due timestamp.
        - Status initialized to 'scheduled' with attempt_count=0.
        - Audit trail logging.
        """
        # Validate commitment
        commitment = (
            self.db.query(Commitment).filter(Commitment.id == commitment_id).first()
        )
        if not commitment:
            raise ReminderNotFoundError(f"Commitment {commitment_id} not found.")

        user = (
            self.db.query(User)
            .filter(User.id == (user_id or commitment.user_id))
            .first()
        )
        if not user:
            raise ReminderNotFoundError("User not found.")

        # Ensure due_at is UTC
        utc_due = ensure_utc(due_at)

        # Idempotency check
        key = idempotency_key or f"rem-{uuid.uuid4().hex[:12]}"
        existing = (
            self.db.query(Reminder).filter(Reminder.idempotency_key == key).first()
        )
        if existing:
            return existing

        now = utc_now()
        reminder = Reminder(
            id=uuid.uuid4(),
            commitment_id=commitment.id,
            due_at=utc_due,
            channel=channel,
            status="scheduled",
            attempt_count=0,
            idempotency_key=key,
            created_at=now,
            updated_at=now,
        )
        self.db.add(reminder)

        # Audit event
        audit = AuditEvent(
            id=uuid.uuid4(),
            user_id=user.id,
            entity_type="reminder",
            entity_id=reminder.id,
            action="create_reminder",
            actor="agent",
            payload={
                "commitment_id": str(commitment.id),
                "due_at": utc_due.isoformat(),
                "channel": channel,
                "idempotency_key": key,
            },
            created_at=now,
        )
        self.db.add(audit)
        self.db.commit()
        self.db.refresh(reminder)
        return reminder

    def get_reminder(self, reminder_id: uuid.UUID) -> Reminder:
        """Retrieve a reminder by ID along with its delivery attempts."""
        reminder = self.db.query(Reminder).filter(Reminder.id == reminder_id).first()
        if not reminder:
            raise ReminderNotFoundError(f"Reminder {reminder_id} not found.")
        return reminder

    def list_reminders(
        self,
        user_id: uuid.UUID | None = None,
        status: str | None = None,
        commitment_id: uuid.UUID | None = None,
    ) -> list[Reminder]:
        """List reminders filtered by status or commitment."""
        query = self.db.query(Reminder).join(
            Commitment, Commitment.id == Reminder.commitment_id
        )
        if user_id:
            query = query.filter(Commitment.user_id == user_id)
        if status:
            query = query.filter(Reminder.status == status)
        if commitment_id:
            query = query.filter(Reminder.commitment_id == commitment_id)

        return query.order_by(Reminder.due_at.asc()).all()

    def cancel_reminder(
        self,
        reminder_id: uuid.UUID,
        user_id: uuid.UUID | None = None,
    ) -> Reminder:
        """Cancel a pending or retrying reminder.

        Cannot cancel a reminder that is already 'delivered'.
        """
        reminder = self.get_reminder(reminder_id)

        if reminder.status == "delivered":
            raise ReminderStateError(
                f"Cannot cancel reminder {reminder_id} because it has already been delivered."
            )
        if reminder.status == "cancelled":
            return reminder

        now = utc_now()
        reminder.status = "cancelled"
        reminder.updated_at = now

        audit = AuditEvent(
            id=uuid.uuid4(),
            user_id=reminder.commitment.user_id,
            entity_type="reminder",
            entity_id=reminder.id,
            action="cancel_reminder",
            actor="person",
            payload={"status_before": reminder.status},
            created_at=now,
        )
        self.db.add(audit)
        self.db.commit()
        self.db.refresh(reminder)
        return reminder
