import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.models.database import Base, engine
from app.models.seed import seed_database

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("daypilot")


from app.reminders.scheduler import (
    shutdown_reminder_scheduler,
    start_reminder_scheduler,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing DayPilot backend...")
    if settings.ENVIRONMENT != "test":
        Base.metadata.create_all(bind=engine)
        seed_database()
        start_reminder_scheduler()
    logger.info("DayPilot backend initialized.")
    yield
    logger.info("Shutting down DayPilot backend...")
    if settings.ENVIRONMENT != "test":
        shutdown_reminder_scheduler()


app = FastAPI(
    title="DayPilot API",
    description=(
        "Personal admin agent that turns messy requests into tracked commitments, "
        "plans around fixed events, and never writes to a calendar or sends a message without approval."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# CORS Middleware for Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.api.audit import router as audit_router
from app.api.commitments import router as commitments_router
from app.api.daily_review import router as daily_review_router
from app.api.inputs import router as inputs_router
from app.api.plans import router as plans_router
from app.api.proposals import router as proposals_router
from app.api.reminders import router as reminders_router

app.include_router(inputs_router, prefix=settings.API_V1_STR)
app.include_router(commitments_router, prefix=settings.API_V1_STR)
app.include_router(plans_router, prefix=settings.API_V1_STR)
app.include_router(proposals_router, prefix=settings.API_V1_STR)
app.include_router(reminders_router, prefix=settings.API_V1_STR)
app.include_router(audit_router, prefix=settings.API_V1_STR)
app.include_router(daily_review_router, prefix=settings.API_V1_STR)


@app.get("/health", tags=["System"])
def health_check():
    return {
        "status": "healthy",
        "service": settings.PROJECT_NAME,
        "environment": settings.ENVIRONMENT,
        "database": "connected",
    }


@app.get("/", tags=["System"])
def root():
    return {
        "name": "DayPilot API",
        "version": "0.1.0",
        "docs": "/docs",
        "principles": [
            "Proposal before action",
            "Show the source",
            "Conflicts are visible, never silent",
            "Status is honest",
            "Calm by default",
        ],
    }
