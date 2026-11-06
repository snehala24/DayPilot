import logging
import threading

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.integrations.notifications import SimulatedNotificationAdapter
from app.models.database import SessionLocal
from app.reminders.manager import RetryPolicy
from app.reminders.worker import ReminderDispatcher

logger = logging.getLogger("daypilot.reminders.scheduler")

_scheduler: BackgroundScheduler | None = None
_lock = threading.Lock()


def run_scheduled_dispatch() -> None:
    """Invoked periodically by APScheduler to process due reminders."""
    # Ensure only one worker execution runs at a time
    if not _lock.acquire(blocking=False):
        logger.info(
            "Previous reminder dispatch job is still running. Skipping this tick."
        )
        return

    try:
        db = SessionLocal()
        try:
            adapter = SimulatedNotificationAdapter(default_mode="success")
            dispatcher = ReminderDispatcher(
                db=db,
                adapter=adapter,
                retry_policy=RetryPolicy(),
            )
            summary = dispatcher.dispatch_due_reminders()
            if summary.processed_count > 0 or summary.recovered_count > 0:
                logger.info(
                    "Scheduled reminder dispatch completed: %d processed, %d delivered, %d retried, %d failed, %d recovered",
                    summary.processed_count,
                    summary.delivered_count,
                    summary.retried_count,
                    summary.failed_count,
                    summary.recovered_count,
                )
        finally:
            db.close()
    except Exception:
        logger.exception("Error during scheduled reminder dispatch")
    finally:
        _lock.release()


def start_reminder_scheduler(interval_seconds: int = 60) -> BackgroundScheduler:
    """Initialize and start the background reminder scheduler."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return _scheduler

    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(
        func=run_scheduled_dispatch,
        trigger=IntervalTrigger(seconds=interval_seconds),
        id="reminder_dispatch_job",
        name="Dispatch due reminders",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    logger.info(
        "Reminder background scheduler started (interval: %ds).", interval_seconds
    )
    return _scheduler


def shutdown_reminder_scheduler() -> None:
    """Gracefully shutdown the background reminder scheduler."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Reminder background scheduler stopped.")
