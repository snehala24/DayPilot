import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.agent.client import LLMClient, get_llm_client
from app.models.database import get_db, utc_now
from app.models.entities import User
from app.review.engine import build_daily_review
from app.review.schemas import DailyReviewResponse

logger = logging.getLogger("daypilot.api.daily_review")
router = APIRouter(prefix="/daily-review", tags=["Daily Review"])


@router.get("", response_model=DailyReviewResponse)
def get_daily_review(
    review_date: date | None = Query(
        None, description="Date to review; defaults to today"
    ),
    db: Session = Depends(get_db),
    llm_client: LLMClient = Depends(get_llm_client),
):
    """Retrieve deterministic daily review based on persisted DayPilot data.

    Invariants:
    - Factual observations reflect only verified database state.
    - Zero hallucinated completion states, productivity scores, or activity metrics.
    - Suggestions are strictly differentiated from facts.
    - Read-only: Never alters database state or triggers external writes.
    """
    user = db.query(User).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="System user not initialized. Please ensure seed data is applied.",
        )

    target_date = review_date or utc_now().date()
    return build_daily_review(
        db=db,
        user=user,
        review_date=target_date,
        llm_client=llm_client if hasattr(llm_client, "generate") else None,
    )
