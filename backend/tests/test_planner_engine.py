import uuid
import zoneinfo
from datetime import UTC, date, datetime

import pytest

from app.models.database import utc_now
from app.models.entities import CalendarEvent, Commitment
from app.planner.engine import (
    DayPlanner,
    PlanningResult,
)


@pytest.fixture
def test_date() -> date:
    return date(2026, 11, 10)


@pytest.fixture
def user_tz() -> str:
    return "UTC"


def make_commitment(
    title: str,
    estimate_minutes: int = 60,
    priority: int = 3,
    due_at: datetime | None = None,
    dependencies: list | None = None,
) -> Commitment:
    return Commitment(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        title=title,
        priority=priority,
        estimate_minutes=estimate_minutes,
        due_at=due_at,
        status="open",
        created_at=utc_now(),
        updated_at=utc_now(),
    )


def make_fixed_event(
    title: str,
    starts_at: datetime,
    ends_at: datetime,
    tz: str = "UTC",
) -> CalendarEvent:
    return CalendarEvent(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        source="simulated",
        external_id=f"sim-{uuid.uuid4().hex[:6]}",
        title=title,
        starts_at=starts_at,
        ends_at=ends_at,
        tz=tz,
        is_fixed=True,
        created_at=utc_now(),
        updated_at=utc_now(),
    )


def test_planner_empty_calendar(test_date, user_tz):
    """Scenario: Empty calendar with 3 independent tasks. All must be scheduled without conflicts."""
    planner = DayPlanner(
        user_timezone=user_tz, working_hours_start="09:00", working_hours_end="18:00"
    )

    c1 = make_commitment("Task High Priority", estimate_minutes=60, priority=1)
    c2 = make_commitment("Task Medium Priority", estimate_minutes=120, priority=2)
    c3 = make_commitment("Task Low Priority", estimate_minutes=90, priority=4)

    commitments = [c3, c1, c2]  # submitted out of priority order
    result: PlanningResult = planner.plan(
        plan_date=test_date,
        commitments=commitments,
        calendar_events=[],
        dependencies_map={},
    )

    assert len(result.scheduled_items) == 3
    assert len(result.conflicts) == 0
    assert result.constraints_report["violations_count"] == 0

    # High priority c1 must be scheduled first
    assert result.scheduled_items[0].commitment_id == c1.id
    assert result.scheduled_items[1].commitment_id == c2.id
    assert result.scheduled_items[2].commitment_id == c3.id


def test_planner_respects_fixed_events_and_lunch_break(test_date, user_tz):
    """Scenario: Fixed team standup 10:00 - 11:00 and lunch 13:00 - 14:00.
    Planned tasks must weave around fixed events without any overlap."""
    tz = zoneinfo.ZoneInfo(user_tz)
    fixed_start = datetime.combine(
        test_date, datetime.strptime("10:00", "%H:%M").time(), tzinfo=tz
    ).astimezone(UTC)
    fixed_end = datetime.combine(
        test_date, datetime.strptime("11:00", "%H:%M").time(), tzinfo=tz
    ).astimezone(UTC)
    standup = make_fixed_event("Team Standup", starts_at=fixed_start, ends_at=fixed_end)

    planner = DayPlanner(
        user_timezone=user_tz,
        working_hours_start="09:00",
        working_hours_end="18:00",
        break_blocks=[{"start": "13:00", "end": "14:00", "name": "Lunch"}],
    )

    c1 = make_commitment(
        "Review PR", estimate_minutes=45, priority=1
    )  # should fit 09:00 - 09:45
    c2 = make_commitment(
        "Write Tests", estimate_minutes=90, priority=2
    )  # should fit 11:00 - 12:30

    result = planner.plan(
        plan_date=test_date,
        commitments=[c1, c2],
        calendar_events=[standup],
        dependencies_map={},
    )

    assert len(result.scheduled_items) == 2
    assert len(result.conflicts) == 0
    assert result.constraints_report["violations_count"] == 0

    # Verify standup and lunch non-overlap
    for item in result.scheduled_items:
        # Cannot overlap standup
        assert item.ends_at <= fixed_start or item.starts_at >= fixed_end
        # Cannot overlap lunch 13:00 - 14:00
        lunch_start = datetime.combine(
            test_date, datetime.strptime("13:00", "%H:%M").time(), tzinfo=tz
        ).astimezone(UTC)
        lunch_end = datetime.combine(
            test_date, datetime.strptime("14:00", "%H:%M").time(), tzinfo=tz
        ).astimezone(UTC)
        assert item.ends_at <= lunch_start or item.starts_at >= lunch_end


def test_planner_enforces_dependency_ordering(test_date, user_tz):
    """Scenario: Task B depends on Task A. Task B must start strictly after Task A finishes."""
    planner = DayPlanner(
        user_timezone=user_tz, working_hours_start="09:00", working_hours_end="18:00"
    )

    task_a = make_commitment("Task A (Prerequisite)", estimate_minutes=60, priority=2)
    task_b = make_commitment(
        "Task B (Dependent)", estimate_minutes=60, priority=1
    )  # higher priority, but blocked by A!

    dependencies = {task_b.id: [task_a.id]}

    result = planner.plan(
        plan_date=test_date,
        commitments=[task_b, task_a],
        calendar_events=[],
        dependencies_map=dependencies,
    )

    assert len(result.scheduled_items) == 2
    assert len(result.conflicts) == 0

    sched_a = next(it for it in result.scheduled_items if it.commitment_id == task_a.id)
    sched_b = next(it for it in result.scheduled_items if it.commitment_id == task_b.id)

    # Task A MUST finish before Task B starts
    assert sched_a.ends_at <= sched_b.starts_at


def test_seeded_conflict_insufficient_time_and_alternatives_feasibility(
    test_date, user_tz
):
    """Scenario: 100% seeded conflict detection where commitments exceed total available hours.
    Every conflict must be reported with 2-3 feasible alternatives that pass validation."""
    tz = zoneinfo.ZoneInfo(user_tz)
    # Book calendar from 10:00 to 17:00 with client meetings
    m1_start = datetime.combine(
        test_date, datetime.strptime("10:00", "%H:%M").time(), tzinfo=tz
    ).astimezone(UTC)
    m1_end = datetime.combine(
        test_date, datetime.strptime("17:00", "%H:%M").time(), tzinfo=tz
    ).astimezone(UTC)
    long_meeting = make_fixed_event(
        "All-day Client Workshop", starts_at=m1_start, ends_at=m1_end
    )

    planner = DayPlanner(
        user_timezone=user_tz, working_hours_start="09:00", working_hours_end="18:00"
    )

    # Available time today: 09:00 - 10:00 (60m) and 17:00 - 18:00 (60m). Total = 120m.
    c1 = make_commitment(
        "Morning Task", estimate_minutes=60, priority=1
    )  # Fits 09:00 - 10:00
    c2 = make_commitment(
        "Big 3-Hour Feature Task", estimate_minutes=180, priority=2
    )  # Cannot fit 60m remaining!

    result = planner.plan(
        plan_date=test_date,
        commitments=[c1, c2],
        calendar_events=[long_meeting],
        dependencies_map={},
    )

    # c1 scheduled, c2 conflicting
    assert len(result.scheduled_items) == 1
    assert result.scheduled_items[0].commitment_id == c1.id
    assert len(result.conflicts) == 1

    conflict = result.conflicts[0]
    assert conflict.commitment_id == c2.id
    assert conflict.kind in ["overlap_fixed_event", "insufficient_working_hours"]
    assert len(conflict.alternatives) >= 2

    # Verification: Every alternative must be well-formed and actionable
    for alt in conflict.alternatives:
        assert "action" in alt
        assert "title" in alt
        assert "description" in alt
        if alt["action"] == "reschedule_next_day":
            assert "proposed_start" in alt
        elif alt["action"] == "split_task":
            assert alt["total_duration_minutes"] == 180
            assert sum(p["duration_minutes"] for p in alt["parts"]) == 180


def test_seeded_conflict_deadline_missed(test_date, user_tz):
    """Scenario: Task due at 10:00 AM, but morning 09:00 - 10:30 is occupied by a fixed event."""
    tz = zoneinfo.ZoneInfo(user_tz)
    fixed_start = datetime.combine(
        test_date, datetime.strptime("09:00", "%H:%M").time(), tzinfo=tz
    ).astimezone(UTC)
    fixed_end = datetime.combine(
        test_date, datetime.strptime("10:30", "%H:%M").time(), tzinfo=tz
    ).astimezone(UTC)
    morning_event = make_fixed_event(
        "Morning Keynote", starts_at=fixed_start, ends_at=fixed_end
    )

    deadline = datetime.combine(
        test_date, datetime.strptime("10:00", "%H:%M").time(), tzinfo=tz
    ).astimezone(UTC)
    urgent_task = make_commitment(
        "Submit Grant Application", estimate_minutes=45, priority=1, due_at=deadline
    )

    planner = DayPlanner(
        user_timezone=user_tz, working_hours_start="09:00", working_hours_end="18:00"
    )
    result = planner.plan(
        plan_date=test_date,
        commitments=[urgent_task],
        calendar_events=[morning_event],
        dependencies_map={},
    )

    assert len(result.scheduled_items) == 0
    assert len(result.conflicts) == 1
    conf = result.conflicts[0]
    assert conf.kind == "deadline_missed"
    assert "deadline" in conf.reason.lower()
    assert any(a["action"] == "extend_deadline" for a in conf.alternatives)


def test_planner_fully_booked_day_no_feasible_schedule(test_date, user_tz):
    """Scenario: Calendar is 100% blocked from 09:00 to 18:00.
    All tasks must produce conflicts with alternatives; 0 hard-constraint violations."""
    tz = zoneinfo.ZoneInfo(user_tz)
    day_start = datetime.combine(
        test_date, datetime.strptime("09:00", "%H:%M").time(), tzinfo=tz
    ).astimezone(UTC)
    day_end = datetime.combine(
        test_date, datetime.strptime("18:00", "%H:%M").time(), tzinfo=tz
    ).astimezone(UTC)
    full_day_event = make_fixed_event(
        "All-day Offsite", starts_at=day_start, ends_at=day_end
    )

    planner = DayPlanner(
        user_timezone=user_tz, working_hours_start="09:00", working_hours_end="18:00"
    )
    c1 = make_commitment("Task 1", estimate_minutes=30)
    c2 = make_commitment("Task 2", estimate_minutes=45)

    result = planner.plan(
        plan_date=test_date,
        commitments=[c1, c2],
        calendar_events=[full_day_event],
        dependencies_map={},
    )

    assert len(result.scheduled_items) == 0
    assert len(result.conflicts) == 2
    assert result.constraints_report["violations_count"] == 0


def test_planner_timezone_boundaries():
    """Scenario: User is in Asia/Kolkata (UTC+05:30).
    Working hours 09:00 - 18:00 IST must correspond to 03:30 - 12:30 UTC."""
    planner = DayPlanner(
        user_timezone="Asia/Kolkata",
        working_hours_start="09:00",
        working_hours_end="18:00",
    )
    plan_date = date(2026, 11, 10)

    c = make_commitment("Morning IST task", estimate_minutes=60, priority=1)
    result = planner.plan(
        plan_date=plan_date,
        commitments=[c],
        calendar_events=[],
        dependencies_map={},
    )

    assert len(result.scheduled_items) == 1
    item = result.scheduled_items[0]

    # Convert scheduled start to Asia/Kolkata
    ist_tz = zoneinfo.ZoneInfo("Asia/Kolkata")
    ist_start = item.starts_at.astimezone(ist_tz)
    assert ist_start.hour == 9
    assert ist_start.minute == 0
    # In UTC, 09:00 IST is 03:30 UTC
    assert item.starts_at.hour == 3
    assert item.starts_at.minute == 30
