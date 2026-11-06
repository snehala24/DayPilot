from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "DayPilot"
    API_V1_STR: str = "/api/v1"
    DEBUG: bool = False
    ENVIRONMENT: str = "development"

    # Database
    DATABASE_URL: str = "sqlite:///./daypilot.db"

    # LLM Settings
    GEMINI_API_KEY: str | None = None
    LLM_MODEL: str = "gemini-2.5-flash"

    # Default User & Timezone
    DEFAULT_USER_EMAIL: str = "snehala@daypilot.local"
    DEFAULT_TIMEZONE: str = "UTC"

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()
