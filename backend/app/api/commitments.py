import uuid
import zoneinfo
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.agent.schemas import (
    ConfirmCommitmentsRequest,
    ConfirmCommitmentsResponse,
    ConfirmedCommitmentItem,
)
from app.models.database import get_db, utc_now
from app.models.entities import AuditEvent, Commitment, CommitmentDependency, Note, User

router = APIRouter(prefix="/commitments", tags=["Commitments"])


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

    # 5. Link dependencies
    for idx, candidate in enumerate(payload.commitments):
        current_commit = saved_commitments[idx]
        for dep_title in candidate.dependencies:
            dep_clean = dep_title.strip().lower()
            if dep_clean in title_to_commitment:
                dep_commit = title_to_commitment[dep_clean]
                if dep_commit.id != current_commit.id:
                    dep = CommitmentDependency(
                        commitment_id=current_commit.id,
                        depends_on_id=dep_commit.id,
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
    query = db.query(Commitment)
    if status:
        query = query.filter(Commitment.status == status)
    if project_id:
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
    c = db.query(Commitment).filter(Commitment.id == commitment_id).first()
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
