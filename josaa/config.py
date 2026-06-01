from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg2://josaa:josaa@localhost:5432/josaa"

    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-6"

    # The year served by CurrentORCR.aspx (it has no Year dropdown). Older years
    # are fetched from the archive page which does have a Year dropdown.
    current_year: int = 2025

    headless: bool = True
    request_delay_seconds: float = 1.0


settings = Settings()
