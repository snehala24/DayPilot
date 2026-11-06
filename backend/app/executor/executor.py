import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.integrations.calendar_writer import (
    CalendarWriteError,
    SimulatedCalendarWriteAdapter,
)
from app.models.database import utc_now
from app.models.entities import Approval, AuditEvent, CalendarEvent, Proposal
from app.planner.engine import ensure_utc

logger = logging.getLogger("daypilot.executor")


class ApprovalGateViolationError(Exception):
    """Raised when an attempt is made to execute an action without a valid approved proposal."""


class ReadBackVerificationError(Exception):
    """Raised when read-back verification fails after execution."""


@dataclass
class ExecutionResult:
    proposal_id: uuid.UUID
    status: str  # "verified", "failed", "idempotent_duplicate"
    calendar_event_id: uuid.UUID | None
    details: dict[str, Any]
    error: str | None = None


class ProposalExecutor:
    """The ONLY module authorized to invoke external-write adapters.

    Hard Invariants:
    1. Refuses execution unless a matching Approval row with decision='approved' exists.
    2. Revalidates approval immediately before execution in the database transaction.
    3. Requires matching read-back verification before marking proposal 'verified'.
    4. Records an append-only audit event for every execution and recovery attempt.
    """

    def __init__(self, db: Session):
        self.db = db
        self.write_adapter = SimulatedCalendarWriteAdapter(db=db)

    def execute_proposal(
        self,
        proposal_id: uuid.UUID,
        simulated_fault: str | None = None,
    ) -> ExecutionResult:
        # 1. Fetch proposal
        proposal = self.db.query(Proposal).filter(Proposal.id == proposal_id).first()
        if not proposal:
            raise ApprovalGateViolationError(f"Proposal {proposal_id} does not exist.")

        # 2. Idempotency Check: if already executed or verified, return stored result
        if proposal.status == "verified":
            logger.info(
                "Proposal %s already verified. Returning stored idempotent result.",
                proposal_id,
            )
            event_id = (
                proposal.result.get("calendar_event_id") if proposal.result else None
            )
            return ExecutionResult(
                proposal_id=proposal.id,
                status="idempotent_duplicate",
                calendar_event_id=uuid.UUID(event_id) if event_id else None,
                details=proposal.result or {},
            )

        # 3. Strict Approval Gate Revalidation
        if proposal.status != "approved":
            raise ApprovalGateViolationError(
                f"Unauthorized write rejected! Proposal {proposal_id} is in '{proposal.status}' state, not 'approved'."
            )

        # Validate that an approval record actually exists
        approval = (
            self.db.query(Approval)
            .filter(
                Approval.proposal_id == proposal.id, Approval.decision == "approved"
            )
            .first()
        )
        if not approval:
            raise ApprovalGateViolationError(
                f"Unauthorized write rejected! No approved record exists in approvals table for proposal {proposal_id}."
            )

        # Check expiration
        now = utc_now()
        if proposal.expires_at and ensure_utc(proposal.expires_at) < now:
            proposal.status = "expired"
            self.db.commit()
            raise ApprovalGateViolationError(
                f"Proposal {proposal_id} has expired at {proposal.expires_at}."
            )

        # 4. Mark status 'executed'
        proposal.status = "executed"
        self.db.flush()

        # Fault injection testing: simulate adapter failure
        if simulated_fault == "adapter_error":
            proposal.status = "failed"
            proposal.recovery_status = "needs_attention"
            self._record_audit(
                proposal,
                action="execute_failed",
                result={"error": "Simulated adapter failure"},
                recovery_status="needs_attention",
            )
            self.db.commit()
            return ExecutionResult(
                proposal_id=proposal.id,
                status="failed",
                calendar_event_id=None,
                details={},
                error="Simulated adapter failure",
            )

        # 5. Invoke Write Adapter
        payload = approval.edited_payload or proposal.payload
        try:
            created_event = self._perform_action(proposal, payload)
        except Exception as e:
            logger.error("Adapter write failed for proposal %s: %s", proposal_id, e)
            proposal.status = "failed"
            proposal.recovery_status = "needs_attention"
            self._record_audit(
                proposal,
                action="execute_failed",
                result={"error": str(e)},
                recovery_status="needs_attention",
            )
            self.db.commit()
            return ExecutionResult(
                proposal_id=proposal.id,
                status="failed",
                calendar_event_id=None,
                details={},
                error=str(e),
            )

        # 6. Read-Back Verification
        readback_match, readback_details = self._verify_readback(
            created_event=created_event,
            expected_payload=payload,
            simulated_fault=simulated_fault,
        )

        if not readback_match:
            logger.error(
                "Read-back verification mismatch for proposal %s!", proposal_id
            )
            proposal.status = "failed"
            proposal.recovery_status = "needs_attention"
            proposal.result = {
                "error": "Read-back verification mismatch",
                "details": readback_details,
            }
            self._record_audit(
                proposal,
                action="verification_failed",
                result=proposal.result,
                recovery_status="needs_attention",
            )
            self.db.commit()
            return ExecutionResult(
                proposal_id=proposal.id,
                status="failed",
                calendar_event_id=created_event.id if created_event else None,
                details=readback_details,
                error="Read-back verification mismatch",
            )

        # 7. Verification Succeeded!
        proposal.status = "verified"
        proposal.result = {
            "calendar_event_id": str(created_event.id),
            "external_id": created_event.external_id,
            "title": created_event.title,
            "starts_at": created_event.starts_at.isoformat(),
            "ends_at": created_event.ends_at.isoformat(),
            "verified_at": now.isoformat(),
        }
        self._record_audit(
            proposal,
            action="execute_and_verify",
            result=proposal.result,
            recovery_status="recovered",
        )
        self.db.commit()

        return ExecutionResult(
            proposal_id=proposal.id,
            status="verified",
            calendar_event_id=created_event.id,
            details=proposal.result,
        )

    def _perform_action(
        self, proposal: Proposal, payload: dict[str, Any]
    ) -> CalendarEvent:
        starts_at = ensure_utc(datetime.fromisoformat(payload["starts_at"]))
        ends_at = ensure_utc(datetime.fromisoformat(payload["ends_at"]))
        tz = payload.get("tz", "UTC")
        title = payload["title"]

        if proposal.kind in ["calendar_create", "reschedule"]:
            return self.write_adapter.create_event(
                user_id=proposal.user_id,
                title=title,
                starts_at=starts_at,
                ends_at=ends_at,
                tz=tz,
                idempotency_key=proposal.idempotency_key,
            )
        elif proposal.kind == "calendar_update":
            event_id = uuid.UUID(payload["event_id"])
            return self.write_adapter.update_event(
                user_id=proposal.user_id,
                event_id=event_id,
                updates={
                    "title": title,
                    "starts_at": starts_at,
                    "ends_at": ends_at,
                    "tz": tz,
                },
            )
        else:
            raise CalendarWriteError(f"Unsupported action kind: {proposal.kind}")

    def _verify_readback(
        self,
        created_event: CalendarEvent | None,
        expected_payload: dict[str, Any],
        simulated_fault: str | None = None,
    ) -> tuple[bool, dict[str, Any]]:
        if not created_event:
            return False, {"reason": "Event was not created"}

        # Query fresh from database to verify persistence
        actual = (
            self.db.query(CalendarEvent)
            .filter(CalendarEvent.id == created_event.id)
            .first()
        )
        if not actual:
            return False, {"reason": "Event could not be read back from calendar store"}

        expected_title = expected_payload["title"]
        expected_start = ensure_utc(
            datetime.fromisoformat(expected_payload["starts_at"])
        )
        expected_end = ensure_utc(datetime.fromisoformat(expected_payload["ends_at"]))

        actual_start = ensure_utc(actual.starts_at)
        actual_end = ensure_utc(actual.ends_at)

        # Fault injection
        if simulated_fault == "readback_mismatch":
            return False, {"reason": "Simulated field mismatch on read-back"}

        if actual.title != expected_title:
            return False, {
                "reason": f"Title mismatch: '{actual.title}' vs expected '{expected_title}'"
            }

        if actual_start != expected_start or actual_end != expected_end:
            return False, {
                "reason": f"Time mismatch: [{actual_start}, {actual_end}] vs expected [{expected_start}, {expected_end}]"
            }

        return True, {
            "title": actual.title,
            "starts_at": actual_start.isoformat(),
            "ends_at": actual_end.isoformat(),
        }

    def _record_audit(
        self,
        proposal: Proposal,
        action: str,
        result: dict[str, Any] | None = None,
        recovery_status: str | None = None,
    ) -> None:
        audit = AuditEvent(
            id=uuid.uuid4(),
            user_id=proposal.user_id,
            entity_type="proposal",
            entity_id=proposal.id,
            action=action,
            actor="system",
            payload={
                "kind": proposal.kind,
                "idempotency_key": proposal.idempotency_key,
                "payload": proposal.payload,
            },
            result=result,
            recovery_status=recovery_status,
            created_at=utc_now(),
        )
        self.db.add(audit)
