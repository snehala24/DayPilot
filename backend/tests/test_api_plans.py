from datetime import date

import pytest
from fastapi import HTTPException

from app.api.plans import GeneratePlanRequest, generate_day_plan, get_plan_for_date
from app.models.entities import AuditEvent, Plan


def test_generate_day_plan_api(db_session, seeded_db):
    """Test POST /api/v1/plans generates plan, items, conflicts and audit event."""
    today = date.today()
    req = GeneratePlanRequest(plan_date=today)

    response = generate_day_plan(payload=req, db=db_session)

    assert response.id is not None
    assert response.plan_date == today
    assert response.status == "proposed"
    assert response.constraints_report is not None
    assert response.constraints_report["violations_count"] == 0

    # Verify persisted plan in DB
    saved_plan = db_session.query(Plan).filter(Plan.id == response.id).first()
    assert saved_plan is not None
    assert saved_plan.status == "proposed"

    # Verify audit event
    audit = (
        db_session.query(AuditEvent)
        .filter(
            AuditEvent.entity_type == "plan",
            AuditEvent.entity_id == response.id,
        )
        .first()
    )
    assert audit is not None
    assert audit.action == "generate_plan"


def test_generate_plan_supersedes_previous_plan(db_session, seeded_db):
    """Calling generate plan again for the same date marks the prior plan as superseded."""
    today = date.today()
    req = GeneratePlanRequest(plan_date=today)

    resp1 = generate_day_plan(payload=req, db=db_session)
    resp2 = generate_day_plan(payload=req, db=db_session)

    plan1 = db_session.query(Plan).filter(Plan.id == resp1.id).first()
    plan2 = db_session.query(Plan).filter(Plan.id == resp2.id).first()

    assert plan1.status == "superseded"
    assert plan2.status == "proposed"


def test_get_plan_for_date(db_session, seeded_db):
    """Test GET /api/v1/plans/{date}."""
    today = date.today()
    req = GeneratePlanRequest(plan_date=today)
    gen_resp = generate_day_plan(payload=req, db=db_session)

    fetch_resp = get_plan_for_date(plan_date=today, db=db_session)
    assert fetch_resp.id == gen_resp.id
    assert fetch_resp.plan_date == today

    # Non-existent date returns 404
    future_date = date(2099, 1, 1)
    with pytest.raises(HTTPException) as exc_info:
        get_plan_for_date(plan_date=future_date, db=db_session)
    assert exc_info.value.status_code == 404
