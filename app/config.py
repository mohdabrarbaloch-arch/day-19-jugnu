"""Application settings.

Every knob lives here and is read from the environment. Nothing secret is ever
hardcoded — if a value is missing the app either falls back to a safe default or
refuses to start in production.
"""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- core -------------------------------------------------------------
    app_name: str = "Jugnu"
    environment: str = Field(default="development")
    debug: bool = False
    log_level: str = "INFO"

    # --- security ---------------------------------------------------------
    secret_key: str = Field(default_factory=lambda: secrets.token_urlsafe(48))
    access_token_ttl_minutes: int = 60 * 24 * 7
    algorithm: str = "HS256"
    bcrypt_rounds: int = 12

    # --- database ---------------------------------------------------------
    database_url: str = "sqlite:///./jugnu.db"
    sql_echo: bool = False

    # --- cors -------------------------------------------------------------
    cors_origins: str = "http://localhost:8000,http://127.0.0.1:8000"

    # --- rate limiting ----------------------------------------------------
    rate_limit_enabled: bool = True
    rate_limit_search_per_minute: int = 20
    rate_limit_auth_per_minute: int = 10

    # --- retrieval --------------------------------------------------------
    # Comma-separated provider chain, tried in order until one returns results.
    search_providers: str = "wikipedia,duckduckgo"
    max_sources: int = 6
    fetch_timeout_seconds: float = 8.0
    fetch_max_bytes: int = 2_000_000
    fetch_concurrency: int = 4
    user_agent: str = (
        "JugnuBot/1.0 (+https://github.com/mohdabrarbaloch-arch/day-19-jugnu) python-httpx"
    )

    # --- optional third-party search --------------------------------------
    tavily_api_key: str | None = None
    searxng_base_url: str | None = None

    # --- answer synthesis -------------------------------------------------
    # "extractive" (default, no key needed) or "openai" / "anthropic".
    answer_provider: str = "extractive"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-3-5-haiku-latest"
    llm_timeout_seconds: float = 30.0

    # --- cache ------------------------------------------------------------
    cache_ttl_seconds: int = 300
    cache_max_entries: int = 512

    @field_validator("environment")
    @classmethod
    def _known_env(cls, v: str) -> str:
        allowed = {"development", "staging", "production", "test"}
        v = v.strip().lower()
        if v not in allowed:
            raise ValueError(f"environment must be one of {sorted(allowed)}")
        return v

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def provider_chain(self) -> list[str]:
        return [p.strip().lower() for p in self.search_providers.split(",") if p.strip()]

    @property
    def static_dir(self) -> Path:
        return BASE_DIR / "app" / "static"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
