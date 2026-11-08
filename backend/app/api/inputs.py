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

    # 3. Create original raw note record
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
    db.flush()

    # 4. Run extractor
    user_tz = payload.user_timezone or user.timezone or "UTC"
    active_client = (
        llm_client if hasattr(llm_client, "generate_structured") else get_llm_client()
    )
    extractor = CommitmentExtractor(llm_client=active_client)

    try:
        review = extractor.extract(
            raw_text=payload.raw_text,
            note_id=note.id,
            reference_time=utc_now(),
            user_timezone=user_tz,
        )
        db.commit()
        db.refresh(note)
        return review
    except Exception as e:
        db.rollback()
        logger.exception("Extraction failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Extraction engine failed: {e!s}",
        ) from e
