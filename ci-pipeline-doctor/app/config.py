"""Application settings, loaded from environment / .env file.

All variables are prefixed with ``DOCTOR_`` to avoid collisions.
Defaults are chosen so the app runs offline with zero configuration.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="DOCTOR_",
        extra="ignore",
    )

    # Which analyzer backend to use: "heuristic" | "hybrid" | "gemini" | "groq"
    # "hybrid" = heuristic first (free/instant), LLM only when nothing matches.
    provider: str = "hybrid"

    # LLM credentials / models (only used by the respective providers)
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-1.5-flash"
    groq_api_key: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"

    # GitHub integration
    github_webhook_secret: str | None = None
    github_token: str | None = None

    # Persistence (SQLite). Relative paths resolve against the project root.
    db_path: str = "data/doctor.db"
    enable_history: bool = True

    # App metadata
    app_name: str = "AI CI/CD Pipeline Doctor"


settings = Settings()
