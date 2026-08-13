from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql://flyrank:flyrank@localhost:5432/flyrank"
    app_base_url: str = "http://localhost:8000"

    # Stripe — TEST MODE ONLY, forever. Placeholders live in .env (gitignored).
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""


settings = Settings()
