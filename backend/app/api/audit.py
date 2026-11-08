import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.models.database import get_db
from app.models.entities import AuditEvent, User

router = APIRouter(prefix="/audit-events", tags=["Audit & History"])


class AuditEventResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID | None
    action: str
    actor: str
    payload: dict[str, Any] | None
    result: dict[str, Any] | None
    recovery_status: str | None
    created_at: datetime


@router.get("", response_model=list[AuditEventResponse])
def list_audit_events(
    entity_type: str | None = Query(
        None, description="Filter by entity type (proposal, commitment, reminder, plan)"
    ),
    action: str | None = Query(None, description="Filter by action name"),
    limit: int = Query(100, ge=1, le=500, description="Max audit events to return"),
    db: Session = Depends(get_db),
):
    """Retrieve immutable append-only audit trail ordered by created_at desc."""
    user = db.query(User).first()
    query = db.query(AuditEvent)
    if user:
        query = query.filter(AuditEvent.user_id == user.id)
    if isinstance(entity_type, str):
        query = query.filter(AuditEvent.entity_type == entity_type)
    if isinstance(action, str):
        query = query.filter(AuditEvent.action == action)

    actual_limit = limit if isinstance(limit, int) else 100
    events = query.order_by(AuditEvent.created_at.desc()).limit(actual_limit).all()

    return [
        AuditEventResponse(
            id=e.id,
            user_id=e.user_id,
            entity_type=e.entity_type,
            entity_id=e.entity_id,
            action=e.action,
            actor=e.actor,
            payload=e.payload,
            result=e.result,
            recovery_status=e.recovery_status,
            created_at=e.created_at,
        )
        for e in events
    ]
