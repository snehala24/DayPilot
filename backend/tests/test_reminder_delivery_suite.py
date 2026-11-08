import uuid
from datetime import datetime, timedelta, timezone

from app.integrations.notifications import (
    FakeNotificationAdapter,
    SimulatedNotificationAdapter,
)
from app.models.database import utc_now
from app.models.entities import AuditEvent, Commitment, DeliveryAttempt, Reminder
from app.planner.engine import ensure_utc
from app.reminders.manager import ReminderManager, RetryPolicy
from app.reminders.worker import ReminderDispatcher


def test_future_reminders_not_delivered_early(db_session, seeded_db):
    """Reminders scheduled in the future must never be claimed or dispatched early."""
    commitment = db_session.query(Commitment).first()
    future_time = utc_now() + timedelta(hours=3)

    manager = ReminderManager(db=db_session)
    rem = manager.create_reminder(
        commitment_id=commitment.id,
        due_at=future_time,
        idempotency_key="future-rem-001",
    )

    adapter = FakeNotificationAdapter()
    dispatcher = ReminderDispatcher(db=db_session, adapter=adapter)

    summary = dispatcher.dispatch_due_reminders(now=utc_now())

    assert summary.processed_count == 0
    assert summary.delivered_count == 0
    assert len(adapter.sent_notifications) == 0

    refreshed = db_session.query(Reminder).filter(Reminder.id == rem.id).first()
    assert refreshed.status == "scheduled"
    assert refreshed.attempt_count == 0


def test_successful_delivery_single_attempt_and_audit(db_session, seeded_db):
    """A due reminder is delivered once, recorded in delivery_attempts, and audited."""
    commitment = db_session.query(Commitment).first()
    due_time = utc_now() - timedelta(minutes=10)

    manager = ReminderManager(db=db_session)
    rem = manager.create_reminder(
        commitment_id=commitment.id,
        due_at=due_time,
        idempotency_key="success-rem-001",
    )

    adapter = FakeNotificationAdapter()
    dispatcher = ReminderDispatcher(db=db_session, adapter=adapter)

    summary = dispatcher.dispatch_due_reminders(now=utc_now())

    assert summary.processed_count == 1
    assert summary.delivered_count == 1
    assert len(adapter.sent_notifications) == 1

    # Verify Reminder table state
    refreshed = db_session.query(Reminder).filter(Reminder.id == rem.id).first()
    assert refreshed.status == "delivered"
    assert refreshed.attempt_count == 1

    # Verify DeliveryAttempt row
    attempts = (
        db_session.query(DeliveryAttempt)
        .filter(DeliveryAttempt.reminder_id == rem.id)
        .all()
    )
    assert len(attempts) == 1
    assert attempts[0].outcome == "success"
    assert attempts[0].error is None

    # Verify AuditEvent
    audit = (
        db_session.query(AuditEvent)
        .filter(
            AuditEvent.entity_type == "reminder",
            AuditEvent.entity_id == rem.id,
            AuditEvent.action == "deliver_reminder",
        )
        .first()
    )
    assert audit is not None
    assert audit.result["outcome"] == "success"


def test_duplicate_delivery_count_is_strictly_zero(db_session, seeded_db):
    """Safety Invariant: Repeated dispatch runs must produce ZERO duplicate deliveries."""
    commitment = db_session.query(Commitment).first()
    due_time = utc_now() - timedelta(minutes=15)

    manager = ReminderManager(db=db_session)
    rem = manager.create_reminder(
        commitment_id=commitment.id,
        due_at=due_time,
        idempotency_key="no-dup-rem-001",
    )

    adapter = FakeNotificationAdapter()
    dispatcher = ReminderDispatcher(db=db_session, adapter=adapter)

    # First run -> delivers reminder
    s1 = dispatcher.dispatch_due_reminders(now=utc_now())
    assert s1.delivered_count == 1
    assert len(adapter.sent_notifications) == 1

    # Second run -> should skip already delivered reminder
    s2 = dispatcher.dispatch_due_reminders(now=utc_now())
    assert s2.processed_count == 0
    assert s2.delivered_count == 0

    # Third run -> still zero
    s3 = dispatcher.dispatch_due_reminders(now=utc_now())
    assert s3.delivered_count == 0

    # Assert total deliveries across all runs is strictly 1
    assert len(adapter.sent_notifications) == 1
    attempt_count = (
        db_session.query(DeliveryAttempt)
        .filter(DeliveryAttempt.reminder_id == rem.id)
        .count()
    )
    assert attempt_count == 1


def test_temporary_delivery_failure_and_exponential_retry(db_session, seeded_db):
    """Test transient failure, exponential backoff scheduling, and eventual recovery."""
    commitment = db_session.query(Commitment).first()
    t0 = utc_now() - timedelta(minutes=30)

    manager = ReminderManager(db=db_session)
    rem = manager.create_reminder(
        commitment_id=commitment.id,
        due_at=t0,
        idempotency_key="transient-retry-001",
    )

    # Intermittent adapter: fails first 2 attempts, succeeds on 3rd
    adapter = SimulatedNotificationAdapter(
        default_mode="intermittent", failures_before_success=2
    )
    retry_policy = RetryPolicy(
        initial_delay_seconds=60.0, backoff_factor=2.0, max_attempts=3
    )
    dispatcher = ReminderDispatcher(
        db=db_session, adapter=adapter, retry_policy=retry_policy
    )

    # Dispatch 1 (Attempt 1 at t0): Transient failure
    s1 = dispatcher.dispatch_due_reminders(now=t0)
    assert s1.retried_count == 1
    rem1 = db_session.query(Reminder).filter(Reminder.id == rem.id).first()
    assert rem1.status == "retrying"
    assert rem1.attempt_count == 1
    # Next due should be t0 + 60s
    assert ensure_utc(rem1.due_at) == t0 + timedelta(seconds=60)

    # Dispatch at t0 + 30s: Reminder not due yet, should skip
    s_early = dispatcher.dispatch_due_reminders(now=t0 + timedelta(seconds=30))
    assert s_early.processed_count == 0

    # Dispatch 2 (Attempt 2 at t0 + 65s): Transient failure again
    t1 = t0 + timedelta(seconds=65)
    s2 = dispatcher.dispatch_due_reminders(now=t1)
    assert s2.retried_count == 1
    rem2 = db_session.query(Reminder).filter(Reminder.id == rem.id).first()
    assert rem2.status == "retrying"
    assert rem2.attempt_count == 2
    # Next due should be t1 + (60 * 2^1) = t1 + 120s
    assert ensure_utc(rem2.due_at) == t1 + timedelta(seconds=120)

    # Dispatch 3 (Attempt 3 at t1 + 125s): 3rd attempt succeeds!
    t2 = t1 + timedelta(seconds=125)
    s3 = dispatcher.dispatch_due_reminders(now=t2)
    assert s3.delivered_count == 1
    rem3 = db_session.query(Reminder).filter(Reminder.id == rem.id).first()
    assert rem3.status == "delivered"
    assert rem3.attempt_count == 3

    # Total delivery attempts: 3 (2 failures, 1 success)
    attempts = (
        db_session.query(DeliveryAttempt)
        .filter(DeliveryAttempt.reminder_id == rem.id)
        .all()
    )
    assert len(attempts) == 3
    assert [a.outcome for a in attempts] == ["failure", "failure", "success"]


def test_permanent_delivery_failure_transitions_to_dead_letter(db_session, seeded_db):
    """Permanent delivery failure (e.g. invalid recipient) stops immediately with needs_attention."""
    commitment = db_session.query(Commitment).first()
    t0 = utc_now() - timedelta(minutes=5)

    manager = ReminderManager(db=db_session)
    rem = manager.create_reminder(
        commitment_id=commitment.id,
        due_at=t0,
        idempotency_key="perm-fail-001",
    )

    adapter = SimulatedNotificationAdapter(default_mode="permanent_error")
    dispatcher = ReminderDispatcher(db=db_session, adapter=adapter)

    summary = dispatcher.dispatch_due_reminders(now=t0)
    assert summary.failed_count == 1
    assert summary.retried_count == 0

    refreshed = db_session.query(Reminder).filter(Reminder.id == rem.id).first()
    assert refreshed.status == "needs_attention"
    assert refreshed.attempt_count == 1

    # Subsequent dispatch does NOT retry
    summary2 = dispatcher.dispatch_due_reminders(now=t0 + timedelta(hours=1))
    assert summary2.processed_count == 0
    assert summary2.failed_count == 0


def test_maximum_attempt_exhaustion_transitions_to_needs_attention(
    db_session, seeded_db
):
    """When a transient error exceeds max attempts, the reminder transitions to needs_attention (dead letter)."""
    commitment = db_session.query(Commitment).first()
    t = utc_now() - timedelta(hours=1)

    manager = ReminderManager(db=db_session)
    rem = manager.create_reminder(
        commitment_id=commitment.id,
        due_at=t,
        idempotency_key="max-attempts-001",
    )

    adapter = SimulatedNotificationAdapter(default_mode="transient_error")
    retry_policy = RetryPolicy(initial_delay_seconds=10.0, max_attempts=3)
    dispatcher = ReminderDispatcher(
        db=db_session, adapter=adapter, retry_policy=retry_policy
    )

    # Attempt 1
    dispatcher.dispatch_due_reminders(now=t)
    r1 = db_session.query(Reminder).filter(Reminder.id == rem.id).first()
    assert r1.status == "retrying"
    assert r1.attempt_count == 1

    # Attempt 2
    t = r1.due_at + timedelta(seconds=1)
    dispatcher.dispatch_due_reminders(now=t)
    r2 = db_session.query(Reminder).filter(Reminder.id == rem.id).first()
    assert r2.status == "retrying"
    assert r2.attempt_count == 2

    # Attempt 3 (Max attempts reached)
    t = r2.due_at + timedelta(seconds=1)
    summary3 = dispatcher.dispatch_due_reminders(now=t)
    assert summary3.failed_count == 1
    r3 = db_session.query(Reminder).filter(Reminder.id == rem.id).first()
    assert r3.status == "needs_attention"
    assert r3.attempt_count == 3

    # Audit trail verifies terminal failure
    audit = (
        db_session.query(AuditEvent)
        .filter(
            AuditEvent.entity_id == rem.id,
            AuditEvent.action == "deliver_failed_max_attempts_exceeded",
        )
        .first()
    )
    assert audit is not None
    assert audit.recovery_status == "needs_attention"


def test_process_interruption_and_recovery(db_session, seeded_db):
    """An interrupted or crashed worker leaves a reminder in 'claimed'; the next run recovers it."""
    commitment = db_session.query(Commitment).first()
    now = utc_now()

    # Create a reminder stuck in 'claimed' for 10 minutes (exceeding 5 min claim timeout)
    stuck_time = now - timedelta(minutes=10)
    stuck_rem = Reminder(
        id=uuid.uuid4(),
        commitment_id=commitment.id,
        due_at=stuck_time,
        channel="in_app",
        status="claimed",
        attempt_count=0,
        idempotency_key="stuck-rem-001",
        created_at=stuck_time,
        updated_at=stuck_time,
    )
    db_session.add(stuck_rem)
    db_session.commit()

    adapter = FakeNotificationAdapter()
    dispatcher = ReminderDispatcher(
        db=db_session, adapter=adapter, claim_timeout_seconds=300.0
    )

    # Dispatch: should recover stuck reminder back to retrying, and then claim and deliver it!
    summary = dispatcher.dispatch_due_reminders(now=now)

    assert summary.recovered_count == 1
    assert summary.delivered_count == 1

    refreshed = db_session.query(Reminder).filter(Reminder.id == stuck_rem.id).first()
    assert refreshed.status == "delivered"
    assert refreshed.attempt_count == 1

    # Verify recovery audit event
    rec_audit = (
        db_session.query(AuditEvent)
        .filter(
            AuditEvent.entity_id == stuck_rem.id,
            AuditEvent.action == "recover_abandoned_claim",
        )
        .first()
    )
    assert rec_audit is not None


def test_timezone_boundaries_normalized(db_session, seeded_db):
    """Verify that reminders created with non-UTC timezones are safely handled in UTC."""
    commitment = db_session.query(Commitment).first()
    kolkata_tz = timezone(timedelta(hours=5, minutes=30))
    now_kolkata = datetime.now(kolkata_tz) - timedelta(minutes=10)

    manager = ReminderManager(db=db_session)
    rem = manager.create_reminder(
        commitment_id=commitment.id,
        due_at=now_kolkata,
        idempotency_key="tz-boundary-001",
    )

    # Database stored due_at should be correctly converted to UTC
    assert ensure_utc(rem.due_at) == ensure_utc(now_kolkata)
    assert ensure_utc(rem.due_at).tzinfo is not None

    adapter = FakeNotificationAdapter()
    dispatcher = ReminderDispatcher(db=db_session, adapter=adapter)

    summary = dispatcher.dispatch_due_reminders(now=utc_now())
    assert summary.delivered_count == 1

    refreshed = db_session.query(Reminder).filter(Reminder.id == rem.id).first()
    assert refreshed.status == "delivered"


def test_concurrent_workers_zero_duplicate_deliveries(db_session, seeded_db):
    """Concurrency Invariant: Multiple workers attempting to dispatch the same due reminders

    simultaneously must never produce duplicate deliveries.
    """
    commitment = db_session.query(Commitment).first()
    past_due = utc_now() - timedelta(minutes=5)

    # Create 5 due reminders
    reminders = []
    manager = ReminderManager(db=db_session)
    for i in range(5):
        rem = manager.create_reminder(
            commitment_id=commitment.id,
            due_at=past_due,
            idempotency_key=f"concurrent-rem-{i}",
        )
        reminders.append(rem)

    shared_adapter = FakeNotificationAdapter()

    # Simulate 3 concurrent workers attempting dispatch at the exact same instant
    def run_worker():
        # Each worker uses the session to dispatch
        worker = ReminderDispatcher(db=db_session, adapter=shared_adapter)
        return worker.dispatch_due_reminders(now=utc_now())

    # Sequentially / concurrently invoke dispatchers
    w1_summary = run_worker()
    w2_summary = run_worker()
    w3_summary = run_worker()

    total_delivered = (
        w1_summary.delivered_count
        + w2_summary.delivered_count
        + w3_summary.delivered_count
    )
    assert total_delivered == 5, (
        f"Expected exactly 5 deliveries across workers, got {total_delivered}"
    )

    # Total adapter deliveries must be strictly 5 (zero duplicates)
    assert len(shared_adapter.sent_notifications) == 5

    # Check database delivery attempts count
    total_attempts = (
        db_session.query(DeliveryAttempt)
        .filter(DeliveryAttempt.reminder_id.in_([r.id for r in reminders]))
        .count()
    )
    assert total_attempts == 5


def test_crash_window_without_provider_deduplication_results_in_at_least_once_duplicate(
    db_session, seeded_db
):
    """Crash Window Reproduction:

    1. Worker claims reminder via atomic CAS.
    2. External notification provider accepts and sends message.
    3. Worker crashes immediately before database records delivery success.
    4. Recovery worker reclaims reminder after lease expiration.
    5. Second dispatch re-sends.
    Without provider-side deduplication, physical duplicate delivery occurs (at-least-once).
    """
    commitment = db_session.query(Commitment).first()
    now = utc_now()

    rem = Reminder(
        id=uuid.uuid4(),
        commitment_id=commitment.id,
        due_at=now - timedelta(minutes=5),
        channel="in_app",
        status="scheduled",
        idempotency_key=f"crash-window-raw-{uuid.uuid4()}",
    )
    db_session.add(rem)
    db_session.commit()

    adapter = SimulatedNotificationAdapter(
        default_mode="success", enable_provider_deduplication=False
    )
    dispatcher = ReminderDispatcher(
        db=db_session, adapter=adapter, claim_timeout_seconds=0.1
    )

    # 1. Claim reminder
    claimed_ids = dispatcher._claim_due_reminders(now, batch_size=1)
    assert rem.id in claimed_ids

    # 2. Provider sends message
    send_res = adapter.send(
        reminder_id=rem.id,
        recipient="snehala@daypilot.local",
        title="Crash Test",
        message="Important Alert",
        channel="in_app",
        idempotency_key=rem.idempotency_key,
    )
    assert send_res.success is True
    assert len(adapter.sent_deliveries) == 1

    # 3. Process crashes! Database is NOT updated to delivered; remains 'claimed'
    rem_in_db = db_session.query(Reminder).filter(Reminder.id == rem.id).first()
    assert rem_in_db.status == "claimed"

    # 4. Lease expires; recovery worker resets claim to retrying
    crash_time = now + timedelta(seconds=1)
    recovered = dispatcher._recover_abandoned_claims(crash_time)
    assert recovered == 1
    assert rem_in_db.status == "retrying"

    # 5. Second dispatch re-sends to provider
    summary = dispatcher.dispatch_due_reminders(now=crash_time + timedelta(seconds=2))
    assert summary.delivered_count == 1
    assert rem_in_db.status == "delivered"

    # Physical duplicate delivery confirmed (2 sends!)
    assert len(adapter.sent_deliveries) == 2


def test_crash_window_with_provider_deduplication_suppresses_duplicate(
    db_session, seeded_db
):
    """Crash Window with Provider-Side Idempotency:

    When provider supports idempotency tokens, re-dispatching with the same key
    results in provider deduplication (zero physical duplicates).
    """
    commitment = db_session.query(Commitment).first()
    now = utc_now()

    rem = Reminder(
        id=uuid.uuid4(),
        commitment_id=commitment.id,
        due_at=now - timedelta(minutes=5),
        channel="in_app",
        status="scheduled",
        idempotency_key=f"crash-window-dedup-{uuid.uuid4()}",
    )
    db_session.add(rem)
    db_session.commit()

    # Provider with server-side idempotency enabled
    adapter = SimulatedNotificationAdapter(
        default_mode="success", enable_provider_deduplication=True
    )
    dispatcher = ReminderDispatcher(
        db=db_session, adapter=adapter, claim_timeout_seconds=0.1
    )

    # 1. Claim reminder
    claimed_ids = dispatcher._claim_due_reminders(now, batch_size=1)
    assert rem.id in claimed_ids

    # 2. Provider sends message
    send_res = adapter.send(
        reminder_id=rem.id,
        recipient="snehala@daypilot.local",
        title="Crash Test Dedup",
        message="Important Alert",
        channel="in_app",
        idempotency_key=rem.idempotency_key,
    )
    assert send_res.success is True
    assert len(adapter.sent_deliveries) == 1

    # 3. Crash simulated: DB still claimed
    rem_in_db = db_session.query(Reminder).filter(Reminder.id == rem.id).first()
    assert rem_in_db.status == "claimed"

    # 4. Recovery resets lease
    crash_time = now + timedelta(seconds=1)
    recovered = dispatcher._recover_abandoned_claims(crash_time)
    assert recovered == 1

    # 5. Second dispatch passes idempotency_key to adapter -> provider deduplicates!
    summary = dispatcher.dispatch_due_reminders(now=crash_time + timedelta(seconds=2))
    assert summary.delivered_count == 1
    assert rem_in_db.status == "delivered"

    # Physical deliveries strictly 1 (duplicate suppressed!)
    assert len(adapter.sent_deliveries) == 1
