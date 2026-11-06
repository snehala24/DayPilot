import abc
import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.database import utc_now
from app.models.entities import CalendarEvent


class CalendarAdapter(abc.ABC):
    """Abstract interface for calendar integrations (simulated or external)."""

    @abc.abstractmethod
    def get_events(
        self,
        user_id: uuid.UUID,
        start_dt: datetime,
        end_dt: datetime,
    ) -> list[CalendarEvent]:
        """Retrieve calendar events within the given UTC datetime range."""

    @abc.abstractmethod
    def get_event_by_id(
        self,
        user_id: uuid.UUID,
        event_id: uuid.UUID,
    ) -> CalendarEvent | None:
        """Retrieve a single calendar event by ID."""

    @abc.abstractmethod
    def verify_event_exists(
        self,
        user_id: uuid.UUID,
        title: str,
        starts_at: datetime,
        ends_at: datetime,
    ) -> bool:
        """Read-back verification: verify if an event exists with exact title and time bounds."""


class SimulatedCalendarAdapter(CalendarAdapter):
    """Simulated calendar adapter reading and writing to the database calendar_events table.

    Hard Invariants:
    - Fixed events (is_fixed=True) are strictly immutable to the planner.
    - Provides read-back verification methods for the executor module.
    """

    def __init__(self, db: Session):
        self.db = db

    def get_events(
        self,
        user_id: uuid.UUID,
        start_dt: datetime,
        end_dt: datetime,
    ) -> list[CalendarEvent]:
        """Retrieve events that overlap with [start_dt, end_dt]."""
        return (
            self.db.query(CalendarEvent)
            .filter(
                CalendarEvent.user_id == user_id,
                CalendarEvent.starts_at < end_dt,
                CalendarEvent.ends_at > start_dt,
            )
            .order_by(CalendarEvent.starts_at.asc())
            .all()
        )

    def get_event_by_id(
        self,
        user_id: uuid.UUID,
        event_id: uuid.UUID,
    ) -> CalendarEvent | None:
        return (
            self.db.query(CalendarEvent)
            .filter(
                CalendarEvent.user_id == user_id,
                CalendarEvent.id == event_id,
            )
            .first()
        )

    def verify_event_exists(
        self,
        user_id: uuid.UUID,
        title: str,
        starts_at: datetime,
        ends_at: datetime,
    ) -> bool:
        """Verify whether an event with matching title and time boundaries exists in the store."""
        event = (
            self.db.query(CalendarEvent)
            .filter(
                CalendarEvent.user_id == user_id,
                CalendarEvent.title == title,
                CalendarEvent.starts_at == starts_at,
                CalendarEvent.ends_at == ends_at,
            )
            .first()
        )
        return event is not None

    def add_simulated_event(
        self,
        user_id: uuid.UUID,
        title: str,
        starts_at: datetime,
        ends_at: datetime,
        tz: str = "UTC",
        is_fixed: bool = True,
        external_id: str | None = None,
    ) -> CalendarEvent:
        """Helper for seeding and testing calendar scenarios."""
        ext_id = external_id or f"sim-{uuid.uuid4().hex[:8]}"
        event = CalendarEvent(
            id=uuid.uuid4(),
            user_id=user_id,
            source="simulated",
            external_id=ext_id,
            title=title,
            starts_at=starts_at,
            ends_at=ends_at,
            tz=tz,
            is_fixed=is_fixed,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self.db.add(event)
        self.db.commit()
        self.db.refresh(event)
        return event
