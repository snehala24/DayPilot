from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = BACKEND_DIR / "daypilot.db"


class Settings(BaseSettings):
    PROJECT_NAME: str = "DayPilot"
    API_V1_STR: str = "/api/v1"
    DEBUG: bool = False
    ENVIRONMENT: str = "development"

    # Database
    DATABASE_URL: str = f"sqlite:///{DEFAULT_DB_PATH.as_posix()}"

    # LLM Settings
    LLM_PROVIDER: str = "gemini"
    GEMINI_API_KEY: str | None = None
    LLM_MODEL: str = "gemini-3.1-flash-lite"

    # Default User & Timezone
    DEFAULT_USER_EMAIL: str = "snehala@daypilot.local"
    DEFAULT_TIMEZONE: str = "UTC"

    model_config = SettingsConfigDict(
        env_file=(str(BACKEND_DIR / ".env"), ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
