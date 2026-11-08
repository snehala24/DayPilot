import uuid
import zoneinfo
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agent.schemas import (
    ConfirmCommitmentsRequest,
    ConfirmCommitmentsResponse,
    ConfirmedCommitmentItem,
)
from app.models.database import get_db, utc_now
from app.models.entities import AuditEvent, Commitment, CommitmentDependency, Note, User
from app.planner.engine import ensure_utc

router = APIRouter(prefix="/commitments", tags=["Commitments"])


def check_for_dependency_cycles(
    new_dependencies: list[tuple[uuid.UUID, uuid.UUID]],
    existing_dependencies: list[tuple[uuid.UUID, uuid.UUID]],
) -> None:
    """Build directed graph and detect cycles using 3-state DFS.

    Raises HTTPException 400 if a self-dependency or circular dependency is detected.
    """
    from collections import defaultdict

    adj = defaultdict(set)
    nodes = set()

    for u, v in existing_dependencies + new_dependencies:
        if u == v:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Self-dependency is not permitted.",
            )
        adj[u].add(v)
        nodes.add(u)
        nodes.add(v)

    visited = {}  # 1: visiting (in recursion stack), 2: fully visited

    def dfs(node: uuid.UUID) -> bool:
        visited[node] = 1
        for neighbor in adj[node]:
            if visited.get(neighbor) == 1:
                return True
            if visited.get(neighbor) != 2 and dfs(neighbor):
                return True
        visited[node] = 2
        return False

    for node in nodes:
        if visited.get(node) != 2 and dfs(node):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Circular dependency detected in commitment dependencies.",
            )


@router.post(
    "/confirm",
    response_model=ConfirmCommitmentsResponse,
    status_code=status.HTTP_201_CREATED,
)
def confirm_commitments(
    payload: ConfirmCommitmentsRequest,
    db: Session = Depends(get_db),
):
    """Save reviewed and confirmed commitments to the persistent store.

    Hard Invariants:
    - The person explicitly confirms or edits candidates; nothing is stored automatically.
    - Preserves source_note_id and source_span for full provenance.
    - Idempotency key prevents duplicate inserts.
    - Records an append-only audit event.
    """
    # 1. Fetch user
    user = db.query(User).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="System user not initialized.",
        )

    # 2. Verify note exists
    note = db.query(Note).filter(Note.id == payload.note_id).first()
    if not note:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source note with ID {payload.note_id} not found.",
        )

    # 3. Idempotency check
    if payload.idempotency_key:
        from sqlalchemy import String, cast

        existing_audit = (
            db.query(AuditEvent)
            .filter(
                AuditEvent.entity_type == "commitment",
                AuditEvent.action == "confirm_extraction",
                cast(AuditEvent.payload, String).like(f"%{payload.idempotency_key}%"),
            )
            .first()
        )
        if existing_audit and existing_audit.result:
            # Return idempotent response
            existing_commitments = (
                db.query(Commitment).filter(Commitment.source_note_id == note.id).all()
            )
            items = []
            for ec in existing_commitments:
                dep_ids = [
                    d.depends_on_id
                    for d in db.query(CommitmentDependency)
                    .filter(CommitmentDependency.commitment_id == ec.id)
                    .all()
                ]
                items.append(
                    ConfirmedCommitmentItem(
                        id=ec.id,
                        title=ec.title,
                        description=ec.description,
                        due_at=ec.due_at,
                        due_tz=ec.due_tz,
                        priority=ec.priority,
                        status=ec.status,
                        owner=ec.owner,
                        estimate_minutes=ec.estimate_minutes,
                        source_note_id=ec.source_note_id,
                        dependencies=dep_ids,
                    )
                )
            return ConfirmCommitmentsResponse(
                note_id=note.id,
                confirmed_commitment_ids=[ec.id for ec in existing_commitments],
                commitments=items,
                audit_event_id=existing_audit.id,
                status="idempotent_duplicate",
            )

    # 4. Create confirmed commitments
    saved_commitments: list[Commitment] = []
    title_to_commitment: dict[str, Commitment] = {}

    user_tz_name = user.timezone or "UTC"

    for candidate in payload.commitments:
        # Resolve due_at datetime
        due_at = None
        due_tz = candidate.due_tz or user_tz_name

        if candidate.due_date:
            time_part = candidate.due_time or "23:59"
            dt_str = f"{candidate.due_date} {time_part}"
            try:
                local_dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
                tz = zoneinfo.ZoneInfo(due_tz)
                localized_dt = local_dt.replace(tzinfo=tz)
                due_at = localized_dt.astimezone(UTC)
            except Exception:
                due_at = None

        commitment = Commitment(
            id=uuid.uuid4(),
            user_id=user.id,
            project_id=payload.project_id or note.project_id,
            title=candidate.title,
            description=candidate.description,
            owner=candidate.owner,
            due_at=due_at,
            due_tz=due_tz if due_at else None,
            priority=candidate.priority,
            status="open",
            estimate_minutes=candidate.estimate_minutes,
            source_note_id=note.id,
            source_span=candidate.source_span,
            extraction_confidence=1.0,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        db.add(commitment)
        saved_commitments.append(commitment)
        title_to_commitment[candidate.title.strip().lower()] = commitment

    db.flush()

    # 5. Link dependencies with cycle validation
    new_deps = []
    for idx, candidate in enumerate(payload.commitments):
        current_commit = saved_commitments[idx]
        for dep_title in candidate.dependencies:
            dep_clean = dep_title.strip().lower()
            if dep_clean in title_to_commitment:
                dep_commit = title_to_commitment[dep_clean]
                if dep_commit.id == current_commit.id:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Self-dependency detected for '{current_commit.title}'.",
                    )
                new_deps.append((current_commit.id, dep_commit.id))

    # Fetch existing dependencies for cycle check
    existing_deps_raw = (
        db.query(CommitmentDependency.commitment_id, CommitmentDependency.depends_on_id)
        .join(Commitment, Commitment.id == CommitmentDependency.commitment_id)
        .filter(Commitment.user_id == user.id)
        .all()
    )
    existing_deps = [(row[0], row[1]) for row in existing_deps_raw]

    # Validate against circular dependencies
    check_for_dependency_cycles(new_deps, existing_deps)

    for comm_id, dep_id in new_deps:
        dep = CommitmentDependency(
            commitment_id=comm_id,
            depends_on_id=dep_id,
        )
        db.add(dep)

    # 6. Append-only Audit Event
    audit_id = uuid.uuid4()
    audit_event = AuditEvent(
        id=audit_id,
        user_id=user.id,
        entity_type="commitment",
        entity_id=saved_commitments[0].id if saved_commitments else None,
        action="confirm_extraction",
        actor="person",
        payload={
            "note_id": str(note.id),
            "commitment_count": len(saved_commitments),
            "idempotency_key": payload.idempotency_key,
        },
        result={
            "created_ids": [str(c.id) for c in saved_commitments],
        },
        created_at=utc_now(),
    )
    db.add(audit_event)
    db.commit()

    # 7. Build Response
    items = []
    for c in saved_commitments:
        dep_ids = [
            d.depends_on_id
            for d in db.query(CommitmentDependency)
            .filter(CommitmentDependency.commitment_id == c.id)
            .all()
        ]
        items.append(
            ConfirmedCommitmentItem(
                id=c.id,
                title=c.title,
                description=c.description,
                due_at=c.due_at,
                due_tz=c.due_tz,
                priority=c.priority,
                status=c.status,
                owner=c.owner,
                estimate_minutes=c.estimate_minutes,
                source_note_id=c.source_note_id,
                dependencies=dep_ids,
            )
        )

    return ConfirmCommitmentsResponse(
        note_id=note.id,
        confirmed_commitment_ids=[c.id for c in saved_commitments],
        commitments=items,
        audit_event_id=audit_event.id,
        status="confirmed",
    )


@router.get("", response_model=list[ConfirmedCommitmentItem])
def list_commitments(
    status: str | None = Query(
        None,
        description="Filter by status (open, scheduled, in_progress, done, dropped)",
    ),
    project_id: uuid.UUID | None = Query(None, description="Filter by project"),
    db: Session = Depends(get_db),
):
    """List commitments with optional status and project filters."""
    user = db.query(User).first()
    query = db.query(Commitment)
    if user:
        query = query.filter(Commitment.user_id == user.id)
    if isinstance(status, str):
        query = query.filter(Commitment.status == status)
    if isinstance(project_id, uuid.UUID):
        query = query.filter(Commitment.project_id == project_id)

    commitments = query.order_by(Commitment.created_at.desc()).all()
    results = []
    for c in commitments:
        dep_ids = [
            d.depends_on_id
            for d in db.query(CommitmentDependency)
            .filter(CommitmentDependency.commitment_id == c.id)
            .all()
        ]
        results.append(
            ConfirmedCommitmentItem(
                id=c.id,
                title=c.title,
                description=c.description,
                due_at=c.due_at,
                due_tz=c.due_tz,
                priority=c.priority,
                status=c.status,
                owner=c.owner,
                estimate_minutes=c.estimate_minutes,
                source_note_id=c.source_note_id,
                dependencies=dep_ids,
            )
        )
    return results


@router.get("/{commitment_id}", response_model=ConfirmedCommitmentItem)
def get_commitment(commitment_id: uuid.UUID, db: Session = Depends(get_db)):
    """Retrieve commitment detail with dependencies and provenance."""
    user = db.query(User).first()
    query = db.query(Commitment).filter(Commitment.id == commitment_id)
    if user:
        query = query.filter(Commitment.user_id == user.id)
    c = query.first()
    if not c:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Commitment with ID {commitment_id} not found.",
        )
    dep_ids = [
        d.depends_on_id
        for d in db.query(CommitmentDependency)
        .filter(CommitmentDependency.commitment_id == c.id)
        .all()
    ]
    return ConfirmedCommitmentItem(
        id=c.id,
        title=c.title,
        description=c.description,
        due_at=c.due_at,
        due_tz=c.due_tz,
        priority=c.priority,
        status=c.status,
        owner=c.owner,
        estimate_minutes=c.estimate_minutes,
        source_note_id=c.source_note_id,
        dependencies=dep_ids,
    )


class UpdateCommitmentRequest(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    due_at: datetime | None = None
    due_tz: str | None = None
    priority: int | None = Field(None, ge=1, le=4)
    status: str | None = Field(
        None, pattern="^(open|scheduled|in_progress|done|dropped)$"
    )
    estimate_minutes: int | None = Field(None, ge=1)
    owner: str | None = None


@router.patch("/{commitment_id}", response_model=ConfirmedCommitmentItem)
def update_commitment(
    commitment_id: uuid.UUID,
    payload: UpdateCommitmentRequest,
    db: Session = Depends(get_db),
):
    """Update attributes of an existing confirmed commitment."""
    user = db.query(User).first()
    query = db.query(Commitment).filter(Commitment.id == commitment_id)
    if user:
        query = query.filter(Commitment.user_id == user.id)
    c = query.first()
    if not c:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Commitment with ID {commitment_id} not found.",
        )

    now = utc_now()
    updates = {}

    if payload.title is not None:
        c.title = payload.title.strip()
        updates["title"] = c.title
    if payload.description is not None:
        c.description = payload.description.strip()
        updates["description"] = c.description
    if payload.due_at is not None:
        c.due_at = ensure_utc(payload.due_at)
        updates["due_at"] = c.due_at.isoformat()
    if payload.due_tz is not None:
        c.due_tz = payload.due_tz.strip()
        updates["due_tz"] = c.due_tz
    if payload.priority is not None:
        c.priority = payload.priority
        updates["priority"] = c.priority
    if payload.status is not None:
        c.status = payload.status
        updates["status"] = c.status
    if payload.estimate_minutes is not None:
        c.estimate_minutes = payload.estimate_minutes
        updates["estimate_minutes"] = c.estimate_minutes
    if payload.owner is not None:
        c.owner = payload.owner.strip() or None
        updates["owner"] = c.owner

    c.updated_at = now

    audit = AuditEvent(
        id=uuid.uuid4(),
        user_id=c.user_id,
        entity_type="commitment",
        entity_id=c.id,
        action="update_commitment",
        actor="person",
        payload=updates,
        created_at=now,
    )
    db.add(audit)
    db.commit()
    db.refresh(c)

    dep_ids = [
        d.depends_on_id
        for d in db.query(CommitmentDependency)
        .filter(CommitmentDependency.commitment_id == c.id)
        .all()
    ]

    return ConfirmedCommitmentItem(
        id=c.id,
        title=c.title,
        description=c.description,
        due_at=c.due_at,
        due_tz=c.due_tz,
        priority=c.priority,
        status=c.status,
        owner=c.owner,
        estimate_minutes=c.estimate_minutes,
        source_note_id=c.source_note_id,
        dependencies=dep_ids,
    )
