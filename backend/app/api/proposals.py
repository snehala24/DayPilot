import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.executor.executor import ApprovalGateViolationError, ProposalExecutor
from app.models.database import get_db, utc_now
from app.models.entities import Approval, AuditEvent, Proposal, User
from app.planner.engine import ensure_utc

router = APIRouter(prefix="/proposals", tags=["Proposals & Approval Queue"])


class CreateProposalRequest(BaseModel):
    commitment_id: uuid.UUID | None = Field(
        None, description="Optional associated commitment ID"
    )
    kind: str = Field(
        ...,
        description="Action type: calendar_create, calendar_update, calendar_delete, reschedule",
    )
    payload: dict[str, Any] = Field(
        ..., description="Action payload with event title, starts_at, ends_at, etc."
    )
    reason: str | None = Field(
        None, description="Human-readable justification for the proposal"
    )
    idempotency_key: str | None = Field(None, description="Client idempotency key")


class ApproveProposalRequest(BaseModel):
    reason: str | None = Field(None, description="Optional approval remark")
    edited_payload: dict[str, Any] | None = Field(
        None, description="Optional payload adjustments by user before approving"
    )


class RejectProposalRequest(BaseModel):
    reason: str | None = Field(None, description="Reason for rejection")


class ApprovalDetail(BaseModel):
    decision: str
    decided_by: str
    decided_at: datetime
    reason: str | None


class ProposalResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    commitment_id: uuid.UUID | None
    kind: str
    payload: dict[str, Any]
    reason: str | None
    status: str
    idempotency_key: str
    result: dict[str, Any] | None
    recovery_status: str | None
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime
    approval: ApprovalDetail | None = None


@router.post("", response_model=ProposalResponse, status_code=status.HTTP_201_CREATED)
def create_proposal(
    req: CreateProposalRequest,
    db: Session = Depends(get_db),
):
    """Create a new proposed action in the approval queue.

    Hard Invariant:
    Creating a proposal NEVER executes the action. It remains 'pending' until explicitly approved.
    """
    user = db.query(User).first()
    if not user:
        raise HTTPException(status_code=500, detail="User not initialized.")

    idemp_key = req.idempotency_key or f"prop-{uuid.uuid4().hex[:12]}"

    # Check for existing proposal with this idempotency key
    existing = db.query(Proposal).filter(Proposal.idempotency_key == idemp_key).first()
    if existing:
        return _build_proposal_response(existing)

    now = utc_now()
    proposal = Proposal(
        id=uuid.uuid4(),
        user_id=user.id,
        commitment_id=req.commitment_id,
        kind=req.kind,
        payload=req.payload,
        reason=req.reason,
        status="pending",
        idempotency_key=idemp_key,
        expires_at=now + timedelta(hours=24),  # 24 hour expiration window
        created_at=now,
        updated_at=now,
    )
    db.add(proposal)

    # Record audit event
    audit = AuditEvent(
        id=uuid.uuid4(),
        user_id=user.id,
        entity_type="proposal",
        entity_id=proposal.id,
        action="create_proposal",
        actor="agent",
        payload={
            "kind": req.kind,
            "idempotency_key": idemp_key,
            "payload": req.payload,
        },
        created_at=now,
    )
    db.add(audit)
    db.commit()
    db.refresh(proposal)

    return _build_proposal_response(proposal)


@router.get("", response_model=list[ProposalResponse])
def list_proposals(
    status: str | None = Query(
        None,
        description="Filter by status: pending, approved, rejected, executed, verified, failed, expired",
    ),
    kind: str | None = Query(None, description="Filter by kind"),
    db: Session = Depends(get_db),
):
    """List proposals in the approval queue (oldest first)."""
    query = db.query(Proposal)
    if isinstance(status, str):
        query = query.filter(Proposal.status == status)
    if isinstance(kind, str):
        query = query.filter(Proposal.kind == kind)

    proposals = query.order_by(Proposal.created_at.asc()).all()
    return [_build_proposal_response(p) for p in proposals]


@router.get("/{proposal_id}", response_model=ProposalResponse)
def get_proposal(
    proposal_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """Retrieve details for a specific proposal."""
    p = db.query(Proposal).filter(Proposal.id == proposal_id).first()
    if not p:
        raise HTTPException(
            status_code=404, detail=f"Proposal {proposal_id} not found."
        )
    return _build_proposal_response(p)


@router.post("/{proposal_id}/approve", response_model=ProposalResponse)
def approve_proposal(
    proposal_id: uuid.UUID,
    req: ApproveProposalRequest = None,
    db: Session = Depends(get_db),
):
    """Approve a proposed action and trigger the isolated executor with read-back verification.

    Hard Invariants:
    1. Validates proposal is currently in 'pending' state and unexpired.
    2. Atomically records Approval row before calling Executor.
    3. Executor executes the write adapter and reads back the result.
    4. Only a matching read-back marks the proposal 'verified'.
    """
    req = req or ApproveProposalRequest()

    # 1. Fetch proposal
    proposal = db.query(Proposal).filter(Proposal.id == proposal_id).first()
    if not proposal:
        raise HTTPException(
            status_code=404, detail=f"Proposal {proposal_id} not found."
        )

    # 2. State transition validation
    if proposal.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot approve proposal {proposal_id} in '{proposal.status}' state. Only 'pending' proposals can be approved.",
        )

    # 3. Check expiration
    now = utc_now()
    if proposal.expires_at and ensure_utc(proposal.expires_at) < now:
        proposal.status = "expired"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Proposal {proposal_id} expired at {proposal.expires_at}.",
        )

    # 4. Check if already decided
    existing_approval = (
        db.query(Approval).filter(Approval.proposal_id == proposal.id).first()
    )
    if existing_approval:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Proposal {proposal_id} already has a decision: '{existing_approval.decision}'.",
        )

    # 5. Persist Approval Record
    approval = Approval(
        id=uuid.uuid4(),
        proposal_id=proposal.id,
        decision="approved",
        edited_payload=req.edited_payload,
        decided_by="person",
        decided_at=now,
        reason=req.reason,
        created_at=now,
        updated_at=now,
    )
    db.add(approval)
    proposal.status = "approved"
    proposal.updated_at = now
    db.commit()

    # 6. Invoke Isolated Executor
    executor = ProposalExecutor(db=db)
    try:
        executor.execute_proposal(proposal.id)
    except ApprovalGateViolationError as e:
        raise HTTPException(status_code=403, detail=str(e))

    db.refresh(proposal)
    return _build_proposal_response(proposal)


@router.post("/{proposal_id}/reject", response_model=ProposalResponse)
def reject_proposal(
    proposal_id: uuid.UUID,
    req: RejectProposalRequest = None,
    db: Session = Depends(get_db),
):
    """Reject a proposed action."""
    req = req or RejectProposalRequest()

    proposal = db.query(Proposal).filter(Proposal.id == proposal_id).first()
    if not proposal:
        raise HTTPException(
            status_code=404, detail=f"Proposal {proposal_id} not found."
        )

    if proposal.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot reject proposal {proposal_id} in '{proposal.status}' state.",
        )

    existing_approval = (
        db.query(Approval).filter(Approval.proposal_id == proposal.id).first()
    )
    if existing_approval:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Proposal {proposal_id} already has a decision: '{existing_approval.decision}'.",
        )

    now = utc_now()
    approval = Approval(
        id=uuid.uuid4(),
        proposal_id=proposal.id,
        decision="rejected",
        decided_by="person",
        decided_at=now,
        reason=req.reason,
        created_at=now,
        updated_at=now,
    )
    db.add(approval)
    proposal.status = "rejected"
    proposal.updated_at = now

    audit = AuditEvent(
        id=uuid.uuid4(),
        user_id=proposal.user_id,
        entity_type="proposal",
        entity_id=proposal.id,
        action="reject_proposal",
        actor="person",
        payload={"reason": req.reason},
        created_at=now,
    )
    db.add(audit)
    db.commit()
    db.refresh(proposal)

    return _build_proposal_response(proposal)


def _build_proposal_response(p: Proposal) -> ProposalResponse:
    approval_detail = None
    if p.approval:
        approval_detail = ApprovalDetail(
            decision=p.approval.decision,
            decided_by=p.approval.decided_by,
            decided_at=p.approval.decided_at,
            reason=p.approval.reason,
        )
    return ProposalResponse(
        id=p.id,
        user_id=p.user_id,
        commitment_id=p.commitment_id,
        kind=p.kind,
        payload=p.payload,
        reason=p.reason,
        status=p.status,
        idempotency_key=p.idempotency_key,
        result=p.result,
        recovery_status=p.recovery_status,
        expires_at=p.expires_at,
        created_at=p.created_at,
        updated_at=p.updated_at,
        approval=approval_detail,
    )
