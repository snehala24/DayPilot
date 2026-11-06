import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.agent.client import LLMClient, get_llm_client
from app.agent.extractor import CommitmentExtractor
from app.agent.schemas import ExtractionReview, RawInputRequest
from app.models.database import get_db, utc_now
from app.models.entities import Note, Project, User

logger = logging.getLogger("daypilot.api.inputs")
router = APIRouter(prefix="/inputs", tags=["Inputs & Extraction"])


@router.post("", response_model=ExtractionReview, status_code=status.HTTP_201_CREATED)
def submit_raw_input(
    payload: RawInputRequest,
    db: Session = Depends(get_db),
    llm_client: LLMClient = Depends(get_llm_client),
):
    """Submit unstructured raw text note, persist note, and return extracted commitments for review.

    Hard Invariants:
    - Persists original note text with timestamp for full provenance.
    - NEVER creates confirmed commitments in the database.
    - NEVER triggers external writes or actions.
    - Any missing or ambiguous fields generate clarifying questions.
    """
    # 1. Fetch user (or default seed user)
    user = db.query(User).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="System user not initialized. Please ensure seed data is applied.",
        )

    # 2. Check project if provided
    project_id = payload.project_id
    if project_id:
        proj = (
            db.query(Project)
            .filter(Project.id == project_id, Project.user_id == user.id)
            .first()
        )
        if not proj:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found.",
            )

    # 3. Persist original raw note for complete provenance
    note = Note(
        id=uuid.uuid4(),
        user_id=user.id,
        project_id=project_id,
        raw_text=payload.raw_text,
        captured_at=utc_now(),
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    db.add(note)
    db.commit()
    db.refresh(note)

    # 4. Run extractor
    user_tz = payload.user_timezone or user.timezone or "UTC"
    extractor = CommitmentExtractor(llm_client=llm_client)

    try:
        review = extractor.extract(
            raw_text=payload.raw_text,
            note_id=note.id,
            reference_time=utc_now(),
            user_timezone=user_tz,
        )
        return review
    except Exception:
        logger.exception("Extraction failed")
        # Safe fallback: return empty review tied to the stored note so user can enter manually
        return ExtractionReview(
            note_id=note.id,
            raw_text=payload.raw_text,
            commitments=[],
            questions=[],
            can_confirm_all=False,
        )
