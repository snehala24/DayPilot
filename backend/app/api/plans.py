import uuid
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.integrations.simulated_calendar import SimulatedCalendarAdapter
from app.models.database import get_db, utc_now
from app.models.entities import (
    AuditEvent,
    Commitment,
    CommitmentDependency,
    Conflict,
    Plan,
    PlanItem,
    Preference,
    User,
)
from app.planner.engine import DayPlanner, PlanningResult

router = APIRouter(prefix="/plans", tags=["Day Planner"])


class GeneratePlanRequest(BaseModel):
    plan_date: date = Field(..., description="Target date to generate the day plan for")
    project_id: uuid.UUID | None = Field(None, description="Optional project filter")


class PlanItemResponse(BaseModel):
    id: uuid.UUID
    commitment_id: uuid.UUID
    title: str
    starts_at: datetime
    ends_at: datetime
    estimate_minutes: int
    locked: bool


class ConflictResponse(BaseModel):
    id: uuid.UUID
    commitment_id: uuid.UUID
    commitment_title: str
    event_id: uuid.UUID | None
    kind: str
    reason: str | None
    alternatives: list[dict[str, Any]]


class PlanResponse(BaseModel):
    id: uuid.UUID
    plan_date: date
    status: str
    generated_at: datetime
    items: list[PlanItemResponse]
    conflicts: list[ConflictResponse]
    constraints_report: dict[str, Any] | None


@router.post("", response_model=PlanResponse, status_code=status.HTTP_201_CREATED)
def generate_day_plan(
    payload: GeneratePlanRequest,
    db: Session = Depends(get_db),
):
    """Generate a constraint-validated daily plan for the specified date.

    Hard Invariants:
    - Zero violations of fixed events, deadlines, working hours, and dependencies.
    - Every conflict is reported with 2-3 feasible alternatives; nothing moves silently.
    - Emits a plan proposal without writing to external calendars.
    """
    # 1. Fetch user
    user = db.query(User).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="System user not found.",
        )

    # 2. Fetch user preferences
    user_tz = user.timezone or "UTC"
    pref_wh = (
        db.query(Preference)
        .filter(Preference.user_id == user.id, Preference.key == "working_hours")
        .first()
    )

    wh_start = "09:00"
    wh_end = "18:00"
    if pref_wh and isinstance(pref_wh.value, dict):
        wh_start = pref_wh.value.get("start", "09:00")
        wh_end = pref_wh.value.get("end", "18:00")
        user_tz = pref_wh.value.get("timezone", user_tz)

    pref_buffers = (
        db.query(Preference)
        .filter(Preference.user_id == user.id, Preference.key == "planning_buffers")
        .first()
    )
    lunch_break = [{"start": "13:00", "end": "14:00", "name": "Lunch"}]
    if pref_buffers and isinstance(pref_buffers.value, dict):
        lb = pref_buffers.value.get("lunch_break")
        if lb:
            lunch_break = [lb]

    # 3. Retrieve open commitments
    commit_query = db.query(Commitment).filter(
        Commitment.user_id == user.id,
        Commitment.status.in_(["open", "scheduled"]),
    )
    if payload.project_id:
        commit_query = commit_query.filter(Commitment.project_id == payload.project_id)
    commitments = commit_query.all()

    # 4. Retrieve calendar events via SimulatedCalendarAdapter
    adapter = SimulatedCalendarAdapter(db=db)
    # Query span covers 36 hours around plan_date to capture all overlaps across zones
    day_start_utc = datetime(
        payload.plan_date.year,
        payload.plan_date.month,
        payload.plan_date.day,
        0,
        0,
        tzinfo=utc_now().tzinfo,
    )
    day_end_utc = day_start_utc + timedelta(days=2)
    events = adapter.get_events(
        user_id=user.id, start_dt=day_start_utc, end_dt=day_end_utc
    )

    # 5. Retrieve dependencies
    all_commit_ids = [c.id for c in commitments]
    dep_rows = (
        db.query(CommitmentDependency)
        .filter(CommitmentDependency.commitment_id.in_(all_commit_ids))
        .all()
    )
    dependencies_map: dict[uuid.UUID, list[uuid.UUID]] = {}
    for d in dep_rows:
        dependencies_map.setdefault(d.commitment_id, []).append(d.depends_on_id)

    # 6. Run Deterministic Planner
    planner = DayPlanner(
        user_timezone=user_tz,
        working_hours_start=wh_start,
        working_hours_end=wh_end,
        break_blocks=lunch_break,
    )
    result: PlanningResult = planner.plan(
        plan_date=payload.plan_date,
        commitments=commitments,
        calendar_events=events,
        dependencies_map=dependencies_map,
    )

    # 7. Supersede any existing plans for this date
    existing_plans = (
        db.query(Plan)
        .filter(
            Plan.user_id == user.id,
            Plan.plan_date == payload.plan_date,
            Plan.status.in_(["draft", "proposed"]),
        )
        .all()
    )
    for ep in existing_plans:
        ep.status = "superseded"

    # 8. Persist new Plan, PlanItems, and Conflicts
    plan = Plan(
        id=uuid.uuid4(),
        user_id=user.id,
        plan_date=payload.plan_date,
        status="proposed",
        constraints_report=result.constraints_report,
        generated_at=utc_now(),
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    db.add(plan)
    db.flush()

    response_items: list[PlanItemResponse] = []
    for item in result.scheduled_items:
        pi = PlanItem(
            id=uuid.uuid4(),
            plan_id=plan.id,
            commitment_id=item.commitment_id,
            starts_at=item.starts_at,
            ends_at=item.ends_at,
            locked=False,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        db.add(pi)
        response_items.append(
            PlanItemResponse(
                id=pi.id,
                commitment_id=item.commitment_id,
                title=item.title,
                starts_at=item.starts_at,
                ends_at=item.ends_at,
                estimate_minutes=item.estimate_minutes,
                locked=False,
            )
        )

    response_conflicts: list[ConflictResponse] = []
    for conf in result.conflicts:
        c_entity = Conflict(
            id=uuid.uuid4(),
            plan_id=plan.id,
            commitment_id=conf.commitment_id,
            event_id=conf.event_id,
            kind=conf.kind,
            alternatives=conf.alternatives,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        db.add(c_entity)
        response_conflicts.append(
            ConflictResponse(
                id=c_entity.id,
                commitment_id=conf.commitment_id,
                commitment_title=conf.commitment_title,
                event_id=conf.event_id,
                kind=conf.kind,
                reason=conf.reason,
                alternatives=conf.alternatives,
            )
        )

    # 9. Audit Event
    audit = AuditEvent(
        id=uuid.uuid4(),
        user_id=user.id,
        entity_type="plan",
        entity_id=plan.id,
        action="generate_plan",
        actor="agent",
        payload={
            "plan_date": str(payload.plan_date),
            "commitments_considered": len(commitments),
        },
        result={
            "scheduled_items_count": len(response_items),
            "conflicts_count": len(response_conflicts),
        },
        created_at=utc_now(),
    )
    db.add(audit)
    db.commit()

    return PlanResponse(
        id=plan.id,
        plan_date=plan.plan_date,
        status=plan.status,
        generated_at=plan.generated_at,
        items=response_items,
        conflicts=response_conflicts,
        constraints_report=plan.constraints_report,
    )


@router.get("/{plan_date}", response_model=PlanResponse)
def get_plan_for_date(
    plan_date: date,
    db: Session = Depends(get_db),
):
    """Retrieve the current active plan for a specific date."""
    user = db.query(User).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    plan = (
        db.query(Plan)
        .filter(
            Plan.user_id == user.id,
            Plan.plan_date == plan_date,
            Plan.status.in_(["proposed", "accepted", "draft"]),
        )
        .order_by(Plan.created_at.desc())
        .first()
    )
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active plan found for date {plan_date}.",
        )

    items = []
    for pi in plan.items:
        items.append(
            PlanItemResponse(
                id=pi.id,
                commitment_id=pi.commitment_id,
                title=pi.commitment.title if pi.commitment else "Task",
                starts_at=pi.starts_at,
                ends_at=pi.ends_at,
                estimate_minutes=int((pi.ends_at - pi.starts_at).total_seconds() / 60),
                locked=pi.locked,
            )
        )

    conflicts = []
    for cf in plan.conflicts:
        conflicts.append(
            ConflictResponse(
                id=cf.id,
                commitment_id=cf.commitment_id,
                commitment_title=cf.commitment.title if cf.commitment else "Task",
                event_id=cf.event_id,
                kind=cf.kind,
                reason=None,
                alternatives=cf.alternatives,
            )
        )

    return PlanResponse(
        id=plan.id,
        plan_date=plan.plan_date,
        status=plan.status,
        generated_at=plan.generated_at,
        items=items,
        conflicts=conflicts,
        constraints_report=plan.constraints_report,
    )
