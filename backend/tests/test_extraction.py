import uuid
from datetime import UTC, datetime

from app.agent.client import FakeLLMClient
from app.agent.extractor import CommitmentExtractor
from app.agent.schemas import ExtractedCommitment, RawExtractionResult


def test_extraction_basic():
    fake_client = FakeLLMClient()
    fake_client.set_canned_response(
        "Submit the paper",
        RawExtractionResult(
            commitments=[
                ExtractedCommitment(
                    title="Submit the paper",
                    due_date="2026-11-20",
                    due_time="17:00",
                    priority=2,
                    owner="Alice",
                )
            ]
        ),
    )

    extractor = CommitmentExtractor(llm_client=fake_client)
    raw_text = "Submit the paper by 2026-11-20 17:00 assigned to Alice."
    note_id = uuid.uuid4()
    review = extractor.extract(raw_text=raw_text, note_id=note_id)

    assert review.note_id == note_id
    assert len(review.commitments) == 1
    c = review.commitments[0]
    assert c.title == "Submit the paper"
    assert c.due_date == "2026-11-20"
    assert c.due_time == "17:00"
    assert c.owner == "Alice"
    assert c.source_span is not None
    assert "start_char" in c.source_span


def test_ambiguity_detection_soon():
    fake_client = FakeLLMClient()
    fake_client.set_canned_response(
        "Update docs soon",
        RawExtractionResult(
            commitments=[
                ExtractedCommitment(
                    title="Update docs",
                    due_date=None,
                    due_time=None,
                    priority=3,
                )
            ]
        ),
    )

    extractor = CommitmentExtractor(llm_client=fake_client)
    raw_text = "Update docs soon please."
    review = extractor.extract(raw_text=raw_text, note_id=uuid.uuid4())

    assert len(review.commitments) == 1
    assert "due_date" in review.commitments[0].uncertain_fields
    assert len(review.questions) >= 1
    q = review.questions[0]
    assert q.field == "due_date"
    assert "soon" in q.question
    assert review.can_confirm_all is False


def test_ambiguity_detection_next_friday():
    fake_client = FakeLLMClient()
    fake_client.set_canned_response(
        "Team presentation next Friday",
        RawExtractionResult(
            commitments=[
                ExtractedCommitment(
                    title="Team presentation",
                    due_date=None,
                    due_time="14:00",
                    priority=2,
                )
            ]
        ),
    )

    extractor = CommitmentExtractor(llm_client=fake_client)
    raw_text = "Team presentation next Friday at 2pm."
    ref_time = datetime(2026, 11, 5, 10, 0, tzinfo=UTC)  # Thursday
    review = extractor.extract(
        raw_text=raw_text,
        note_id=uuid.uuid4(),
        reference_time=ref_time,
        user_timezone="UTC",
    )

    assert any(q.field == "due_date" for q in review.questions)
    # Check that options differentiate upcoming Friday vs following Friday
    due_date_q = next(q for q in review.questions if q.field == "due_date")
    assert len(due_date_q.options) >= 2


def test_ambiguity_detection_meeting_without_time():
    fake_client = FakeLLMClient()
    fake_client.set_canned_response(
        "Doctor appointment on 2026-11-12",
        RawExtractionResult(
            commitments=[
                ExtractedCommitment(
                    title="Doctor appointment",
                    due_date="2026-11-12",
                    due_time=None,
                    priority=2,
                )
            ]
        ),
    )

    extractor = CommitmentExtractor(llm_client=fake_client)
    raw_text = "Doctor appointment on 2026-11-12."
    review = extractor.extract(raw_text=raw_text, note_id=uuid.uuid4())

    assert any(q.field == "due_time" for q in review.questions)
    time_q = next(q for q in review.questions if q.field == "due_time")
    assert "take place on" in time_q.question


def test_ambiguity_detection_unassigned_owner():
    fake_client = FakeLLMClient()
    fake_client.set_canned_response(
        "Someone needs to deploy",
        RawExtractionResult(
            commitments=[
                ExtractedCommitment(
                    title="Deploy service",
                    due_date=None,
                    due_time=None,
                    owner=None,
                )
            ]
        ),
    )

    extractor = CommitmentExtractor(llm_client=fake_client)
    raw_text = "Someone needs to deploy the service."
    review = extractor.extract(raw_text=raw_text, note_id=uuid.uuid4())

    assert any(q.field == "owner" for q in review.questions)
    owner_q = next(q for q in review.questions if q.field == "owner")
    assert "responsible" in owner_q.question
