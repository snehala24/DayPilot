import abc
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.database import utc_now
from app.models.entities import CalendarEvent


class CalendarWriteError(Exception):
    """Raised when a calendar write fails."""


class CalendarWriteAdapter(abc.ABC):
    """Interface for performing external calendar write operations."""

    @abc.abstractmethod
    def create_event(
        self,
        user_id: uuid.UUID,
        title: str,
        starts_at: datetime,
        ends_at: datetime,
        tz: str = "UTC",
        idempotency_key: str | None = None,
    ) -> CalendarEvent:
        pass

    @abc.abstractmethod
    def update_event(
        self,
        user_id: uuid.UUID,
        event_id: uuid.UUID,
        updates: dict[str, Any],
    ) -> CalendarEvent:
        pass

    @abc.abstractmethod
    def delete_event(
        self,
        user_id: uuid.UUID,
        event_id: uuid.UUID,
    ) -> bool:
        pass


class SimulatedCalendarWriteAdapter(CalendarWriteAdapter):
    """Simulated calendar write adapter.

    Hard Invariant:
    This adapter must ONLY be instantiated and called by the Executor module
    after explicit approval verification.
    """

    def __init__(self, db: Session):
        self.db = db

    def create_event(
        self,
        user_id: uuid.UUID,
        title: str,
        starts_at: datetime,
        ends_at: datetime,
        tz: str = "UTC",
        idempotency_key: str | None = None,
    ) -> CalendarEvent:
        external_id = f"sim-{idempotency_key or uuid.uuid4().hex[:8]}"

        # Check if already exists (idempotency at calendar level)
        existing = (
            self.db.query(CalendarEvent)
            .filter(
                CalendarEvent.source == "simulated",
                CalendarEvent.external_id == external_id,
            )
            .first()
        )
        if existing:
            return existing

        event = CalendarEvent(
            id=uuid.uuid4(),
            user_id=user_id,
            source="simulated",
            external_id=external_id,
            title=title,
            starts_at=starts_at,
            ends_at=ends_at,
            tz=tz,
            is_fixed=False,  # Planned commitment block on calendar
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self.db.add(event)
        self.db.flush()
        return event

    def update_event(
        self,
        user_id: uuid.UUID,
        event_id: uuid.UUID,
        updates: dict[str, Any],
    ) -> CalendarEvent:
        event = (
            self.db.query(CalendarEvent)
            .filter(CalendarEvent.user_id == user_id, CalendarEvent.id == event_id)
            .first()
        )
        if not event:
            raise CalendarWriteError(f"Calendar event {event_id} not found.")

        if "title" in updates:
            event.title = updates["title"]
        if "starts_at" in updates:
            event.starts_at = updates["starts_at"]
        if "ends_at" in updates:
            event.ends_at = updates["ends_at"]
        if "tz" in updates:
            event.tz = updates["tz"]

        event.updated_at = utc_now()
        self.db.flush()
        return event

    def delete_event(
        self,
        user_id: uuid.UUID,
        event_id: uuid.UUID,
    ) -> bool:
        event = (
            self.db.query(CalendarEvent)
            .filter(CalendarEvent.user_id == user_id, CalendarEvent.id == event_id)
            .first()
        )
        if not event:
            return False
        self.db.delete(event)
        self.db.flush()
        return True
