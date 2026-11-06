from datetime import timedelta

from app.integrations.simulated_calendar import SimulatedCalendarAdapter
from app.models.database import utc_now
from app.models.entities import CalendarEvent


def test_simulated_calendar_get_and_verify(db_session, seeded_db):
    user = seeded_db.query(CalendarEvent).first().user
    adapter = SimulatedCalendarAdapter(db=db_session)

    now = utc_now()
    event_start = now + timedelta(hours=1)
    event_end = now + timedelta(hours=2)

    event = adapter.add_simulated_event(
        user_id=user.id,
        title="Sync on Q4 Planning",
        starts_at=event_start,
        ends_at=event_end,
        is_fixed=True,
    )

    assert event.id is not None
    assert event.is_fixed is True

    # 1. Date range query
    events = adapter.get_events(
        user_id=user.id,
        start_dt=now,
        end_dt=now + timedelta(hours=3),
    )
    assert any(e.id == event.id for e in events)

    # 2. Single event retrieval
    fetched = adapter.get_event_by_id(user_id=user.id, event_id=event.id)
    assert fetched is not None
    assert fetched.title == "Sync on Q4 Planning"

    # 3. Read-back verification
    exists = adapter.verify_event_exists(
        user_id=user.id,
        title="Sync on Q4 Planning",
        starts_at=event_start,
        ends_at=event_end,
    )
    assert exists is True

    # Negative verification
    fake_exists = adapter.verify_event_exists(
        user_id=user.id,
        title="Non-existent Meeting",
        starts_at=event_start,
        ends_at=event_end,
    )
    assert fake_exists is False
