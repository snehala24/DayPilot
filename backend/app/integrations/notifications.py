import abc
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.models.database import utc_now


class NotificationError(Exception):
    """Base exception for notification delivery errors."""


class TransientDeliveryError(NotificationError):
    """Temporary delivery failure that should be retried (e.g. network timeout, rate limit)."""


class PermanentDeliveryError(NotificationError):
    """Permanent delivery failure that must NOT be retried (e.g. invalid recipient, unsupported channel)."""


@dataclass
class NotificationResult:
    success: bool
    channel: str
    error: str | None = None
    latency_ms: float = 0.0
    delivered_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class NotificationAdapter(abc.ABC):
    """Abstract interface for notification channels."""

    @abc.abstractmethod
    def send(
        self,
        reminder_id: uuid.UUID,
        recipient: str,
        title: str,
        message: str,
        channel: str = "in_app",
    ) -> NotificationResult:
        """Send a notification for a reminder."""


class FakeNotificationAdapter(NotificationAdapter):
    """In-memory notification adapter for unit tests and verification."""

    def __init__(self):
        self.sent_notifications: list[dict[str, Any]] = []

    def send(
        self,
        reminder_id: uuid.UUID,
        recipient: str,
        title: str,
        message: str,
        channel: str = "in_app",
    ) -> NotificationResult:
        now = utc_now()
        payload = {
            "reminder_id": reminder_id,
            "recipient": recipient,
            "title": title,
            "message": message,
            "channel": channel,
            "timestamp": now,
        }
        self.sent_notifications.append(payload)
        return NotificationResult(
            success=True,
            channel=channel,
            delivered_at=now,
            latency_ms=1.0,
            metadata={"source": "fake"},
        )


class SimulatedNotificationAdapter(NotificationAdapter):
    """Simulated notification delivery adapter supporting deterministic fault injection.

    Modes:
    - 'success': Normal successful delivery.
    - 'transient_error': Simulates temporary network or rate limit failure.
    - 'permanent_error': Simulates unrecoverable failure (e.g. bad address).
    - 'latency': Adds artificial delay before succeeding.
    - 'intermittent': Fails `failures_before_success` times with TransientDeliveryError, then succeeds.
    """

    def __init__(
        self,
        default_mode: str = "success",
        failures_before_success: int = 2,
        simulated_latency_ms: float = 10.0,
    ):
        self.default_mode = default_mode
        self.failures_before_success = failures_before_success
        self.simulated_latency_ms = simulated_latency_ms
        self.failure_counts: dict[uuid.UUID, int] = {}
        self.sent_deliveries: list[dict[str, Any]] = []

    def send(
        self,
        reminder_id: uuid.UUID,
        recipient: str,
        title: str,
        message: str,
        channel: str = "in_app",
    ) -> NotificationResult:
        start_time = time.time()
        now = utc_now()

        # Check mode
        mode = self.default_mode

        if mode == "transient_error":
            raise TransientDeliveryError(
                f"Simulated transient network drop for reminder {reminder_id} on channel {channel}"
            )

        if mode == "permanent_error":
            raise PermanentDeliveryError(
                f"Simulated permanent failure: recipient '{recipient}' is unreachable on channel {channel}"
            )

        if mode == "intermittent":
            current_failures = self.failure_counts.get(reminder_id, 0)
            if current_failures < self.failures_before_success:
                self.failure_counts[reminder_id] = current_failures + 1
                raise TransientDeliveryError(
                    f"Simulated intermittent glitch (attempt {current_failures + 1}/{self.failures_before_success})"
                )

        if mode == "latency":
            time.sleep(self.simulated_latency_ms / 1000.0)

        latency_ms = round((time.time() - start_time) * 1000.0, 2)
        delivery_record = {
            "reminder_id": reminder_id,
            "recipient": recipient,
            "title": title,
            "message": message,
            "channel": channel,
            "timestamp": now,
            "latency_ms": latency_ms,
        }
        self.sent_deliveries.append(delivery_record)

        return NotificationResult(
            success=True,
            channel=channel,
            error=None,
            latency_ms=latency_ms,
            delivered_at=now,
            metadata={"delivery_record": delivery_record},
        )
