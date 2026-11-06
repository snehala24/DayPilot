from datetime import timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.database import utc_now
from app.models.entities import (
    Approval,
    CalendarEvent,
    Commitment,
    CommitmentDependency,
    Preference,
    Project,
    Proposal,
    Reminder,
    User,
)


def test_user_creation(db_session):
    user = User(
        email="test_user@daypilot.local",
        timezone="America/New_York",
    )
    db_session.add(user)
    db_session.commit()

    saved = (
        db_session.query(User).filter(User.email == "test_user@daypilot.local").first()
    )
    assert saved is not None
    assert saved.id is not None
    assert saved.timezone == "America/New_York"
    assert saved.created_at is not None


def test_unique_user_email(db_session):
    u1 = User(email="unique@daypilot.local")
    u2 = User(email="unique@daypilot.local")
    db_session.add(u1)
    db_session.commit()

    db_session.add(u2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_commitment_and_dependencies(db_session):
    user = User(email="commit_user@daypilot.local")
    db_session.add(user)
    db_session.commit()

    c1 = Commitment(
        user_id=user.id,
        title="Task 1",
        priority=2,
        status="open",
        estimate_minutes=30,
    )
    c2 = Commitment(
        user_id=user.id,
        title="Task 2",
        priority=1,
        status="open",
        estimate_minutes=45,
    )
    db_session.add_all([c1, c2])
    db_session.commit()

    # c2 depends on c1
    dep = CommitmentDependency(
        commitment_id=c2.id,
        depends_on_id=c1.id,
    )
    db_session.add(dep)
    db_session.commit()

    saved_dep = (
        db_session.query(CommitmentDependency)
        .filter_by(
            commitment_id=c2.id,
            depends_on_id=c1.id,
        )
        .first()
    )
    assert saved_dep is not None


def test_self_dependency_rejected(db_session):
    user = User(email="self_dep@daypilot.local")
    db_session.add(user)
    db_session.commit()

    c = Commitment(
        user_id=user.id,
        title="Self depending task",
    )
    db_session.add(c)
    db_session.commit()

    bad_dep = CommitmentDependency(
        commitment_id=c.id,
        depends_on_id=c.id,
    )
    db_session.add(bad_dep)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_commitment_priority_constraint(db_session):
    user = User(email="priority@daypilot.local")
    db_session.add(user)
    db_session.commit()

    bad_commit = Commitment(
        user_id=user.id,
        title="Invalid Priority",
        priority=5,  # Valid is 1 to 4
    )
    db_session.add(bad_commit)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_commitment_status_constraint(db_session):
    user = User(email="status@daypilot.local")
    db_session.add(user)
    db_session.commit()

    bad_status = Commitment(
        user_id=user.id,
        title="Invalid Status",
        status="invalid_status_xyz",
    )
    db_session.add(bad_status)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_calendar_event_time_check(db_session):
    user = User(email="cal@daypilot.local")
    db_session.add(user)
    db_session.commit()

    now = utc_now()
    # starts_at after ends_at should fail
    bad_event = CalendarEvent(
        user_id=user.id,
        source="simulated",
        external_id="bad_time_1",
        title="Backwards Time Meeting",
        starts_at=now + timedelta(hours=2),
        ends_at=now + timedelta(hours=1),
        tz="UTC",
    )
    db_session.add(bad_event)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_proposal_idempotency_key_unique(db_session):
    user = User(email="proposal_user@daypilot.local")
    db_session.add(user)
    db_session.commit()

    p1 = Proposal(
        user_id=user.id,
        kind="calendar_create",
        payload={"title": "Test Event"},
        idempotency_key="unique-key-12345",
    )
    db_session.add(p1)
    db_session.commit()

    # Second proposal with same idempotency key must fail
    p2 = Proposal(
        user_id=user.id,
        kind="calendar_create",
        payload={"title": "Duplicate Event"},
        idempotency_key="unique-key-12345",
    )
    db_session.add(p2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_single_approval_per_proposal(db_session):
    user = User(email="approval_user@daypilot.local")
    db_session.add(user)
    db_session.commit()

    prop = Proposal(
        user_id=user.id,
        kind="calendar_create",
        payload={"title": "Meeting"},
        idempotency_key="prop-key-app-1",
    )
    db_session.add(prop)
    db_session.commit()

    app1 = Approval(
        proposal_id=prop.id,
        decision="approved",
        decided_by="person",
    )
    db_session.add(app1)
    db_session.commit()

    # Second approval for the same proposal must be rejected by unique constraint
    app2 = Approval(
        proposal_id=prop.id,
        decision="rejected",
        decided_by="person",
    )
    db_session.add(app2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_reminder_idempotency_key_unique(db_session):
    user = User(email="rem_user@daypilot.local")
    db_session.add(user)
    db_session.commit()

    c = Commitment(user_id=user.id, title="Follow up item")
    db_session.add(c)
    db_session.commit()

    now = utc_now()
    r1 = Reminder(
        commitment_id=c.id,
        due_at=now + timedelta(hours=1),
        channel="in_app",
        idempotency_key="rem-idemp-001",
    )
    db_session.add(r1)
    db_session.commit()

    r2 = Reminder(
        commitment_id=c.id,
        due_at=now + timedelta(hours=1),
        channel="in_app",
        idempotency_key="rem-idemp-001",
    )
    db_session.add(r2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_seed_database_populated(seeded_db):
    user = seeded_db.query(User).filter(User.email == "snehala@daypilot.local").first()
    assert user is not None
    assert user.timezone == "Asia/Kolkata"

    projects = seeded_db.query(Project).filter(Project.user_id == user.id).all()
    assert len(projects) >= 1
    assert projects[0].name == "DayPilot MVP"

    prefs = seeded_db.query(Preference).filter(Preference.user_id == user.id).all()
    assert len(prefs) >= 2
    pref_keys = [p.key for p in prefs]
    assert "working_hours" in pref_keys
    assert "planning_buffers" in pref_keys

    events = (
        seeded_db.query(CalendarEvent).filter(CalendarEvent.user_id == user.id).all()
    )
    assert len(events) >= 2
    assert all(e.is_fixed is True for e in events)

    commits = seeded_db.query(Commitment).filter(Commitment.user_id == user.id).all()
    assert len(commits) >= 2

    # Check dependency between seeded commitments
    deps = seeded_db.query(CommitmentDependency).all()
    assert len(deps) >= 1
