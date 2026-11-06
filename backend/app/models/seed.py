import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.database import SessionLocal, utc_now
from app.models.entities import (
    CalendarEvent,
    Commitment,
    CommitmentDependency,
    Preference,
    Project,
    User,
)

# Deterministic Seed UUIDs
SEED_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
SEED_PROJECT_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")


def seed_database(db: Session = None) -> User:
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        # 1. User
        user = db.query(User).filter(User.id == SEED_USER_ID).first()
        if not user:
            user = User(
                id=SEED_USER_ID,
                email="snehala@daypilot.local",
                timezone="Asia/Kolkata",
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            db.add(user)
            db.flush()

        # 2. Project
        project = db.query(Project).filter(Project.id == SEED_PROJECT_ID).first()
        if not project:
            project = Project(
                id=SEED_PROJECT_ID,
                user_id=user.id,
                name="DayPilot MVP",
                context="Personal admin agent implementation and testing",
                status="active",
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            db.add(project)
            db.flush()

        # 3. Preferences
        pref_working_hours = (
            db.query(Preference)
            .filter(Preference.user_id == user.id, Preference.key == "working_hours")
            .first()
        )
        if not pref_working_hours:
            pref_working_hours = Preference(
                user_id=user.id,
                key="working_hours",
                value={
                    "start": "09:00",
                    "end": "18:00",
                    "days": [1, 2, 3, 4, 5],
                    "timezone": "Asia/Kolkata",
                },
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            db.add(pref_working_hours)

        pref_buffers = (
            db.query(Preference)
            .filter(Preference.user_id == user.id, Preference.key == "planning_buffers")
            .first()
        )
        if not pref_buffers:
            pref_buffers = Preference(
                user_id=user.id,
                key="planning_buffers",
                value={
                    "transition_buffer_minutes": 15,
                    "lunch_break": {"start": "13:00", "end": "14:00"},
                },
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            db.add(pref_buffers)

        # 4. Fixed Simulated Calendar Events for Today
        now = utc_now()
        today = now.date()
        base_dt = datetime(today.year, today.month, today.day, 0, 0, tzinfo=UTC)

        # Event 1: Team Standup 04:00 UTC (09:30 IST)
        standup_start = base_dt + timedelta(hours=4, minutes=0)
        standup_end = base_dt + timedelta(hours=4, minutes=30)

        event1 = (
            db.query(CalendarEvent)
            .filter(
                CalendarEvent.source == "simulated",
                CalendarEvent.external_id == f"sim-event-standup-{today}",
            )
            .first()
        )
        if not event1:
            event1 = CalendarEvent(
                user_id=user.id,
                source="simulated",
                external_id=f"sim-event-standup-{today}",
                title="Daily Engineering Sync",
                starts_at=standup_start,
                ends_at=standup_end,
                tz="Asia/Kolkata",
                is_fixed=True,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            db.add(event1)

        # Event 2: Project Architecture Review 08:30 UTC (14:00 IST)
        review_start = base_dt + timedelta(hours=8, minutes=30)
        review_end = base_dt + timedelta(hours=9, minutes=30)

        event2 = (
            db.query(CalendarEvent)
            .filter(
                CalendarEvent.source == "simulated",
                CalendarEvent.external_id == f"sim-event-arch-review-{today}",
            )
            .first()
        )
        if not event2:
            event2 = CalendarEvent(
                user_id=user.id,
                source="simulated",
                external_id=f"sim-event-arch-review-{today}",
                title="Project Architecture Review",
                starts_at=review_start,
                ends_at=review_end,
                tz="Asia/Kolkata",
                is_fixed=True,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            db.add(event2)

        # 5. Sample Commitment: Prepare slide deck
        commit1_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        commit1 = db.query(Commitment).filter(Commitment.id == commit1_id).first()
        if not commit1:
            commit1 = Commitment(
                id=commit1_id,
                user_id=user.id,
                project_id=project.id,
                title="Prepare DayPilot demo presentation",
                description="Draft 5 key slides covering problem, solution, safety and flow",
                owner="Snehala",
                due_at=base_dt + timedelta(hours=12),
                due_tz="Asia/Kolkata",
                priority=1,
                status="open",
                estimate_minutes=60,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            db.add(commit1)

        # Sample Commitment 2 (depends on commit1): Rehearse presentation
        commit2_id = uuid.UUID("00000000-0000-0000-0000-000000000020")
        commit2 = db.query(Commitment).filter(Commitment.id == commit2_id).first()
        if not commit2:
            commit2 = Commitment(
                id=commit2_id,
                user_id=user.id,
                project_id=project.id,
                title="Rehearse demo presentation",
                description="Dry run of the 5 key user journeys",
                owner="Snehala",
                due_at=base_dt + timedelta(hours=14),
                due_tz="Asia/Kolkata",
                priority=2,
                status="open",
                estimate_minutes=45,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            db.add(commit2)
            db.flush()

            # Dependency: commit2 depends on commit1
            dep = CommitmentDependency(
                commitment_id=commit2.id, depends_on_id=commit1.id
            )
            db.add(dep)

        db.commit()
        return user
    except Exception:
        db.rollback()
        raise
    finally:
        if close_db:
            db.close()


if __name__ == "__main__":
    seed_database()
    print("Seed data applied successfully!")
