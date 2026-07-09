"""Application configuration loaded from the environment.

Settings are parsed once at import time into a cached ``Settings`` singleton so
that every layer (API process, Celery worker, Alembic) reads an identical,
fully-validated configuration object.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "staging", "production"]


class Settings(BaseSettings):
    """Strongly-typed, validated application settings.

    Values are read from environment variables (or a local ``.env`` file). All
    fields are explicitly typed to satisfy ``mypy --strict`` and to fail fast on
    a malformed deployment configuration.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ---
    app_name: str = Field(default="Marketplace Service")
    environment: Environment = Field(default="local")
    debug: bool = Field(default=False)
    log_level: str = Field(default="INFO")

    # --- PostgreSQL ---
    postgres_host: str = Field(default="postgres")
    postgres_port: int = Field(default=5432)
    postgres_db: str = Field(default="marketplace")
    postgres_user: str = Field(default="marketplace")
    postgres_password: str = Field(default="change-me")

    # --- Redis ---
    redis_host: str = Field(default="redis")
    redis_port: int = Field(default=6379)
    redis_db: int = Field(default=0)

    # --- Security / JWT ---
    jwt_secret_key: str = Field(default="insecure-development-key")
    jwt_algorithm: str = Field(default="HS256")
    access_token_ttl_seconds: int = Field(default=900)
    refresh_token_ttl_seconds: int = Field(default=604800)
    refresh_cookie_name: str = Field(default="refresh_token")
    refresh_cookie_secure: bool = Field(default=True)
    # Must match where the auth endpoints are actually mounted so the browser
    # sends the cookie back to /refresh and /logout (they live under /api).
    refresh_cookie_path: str = Field(default="/api/v1/auth")

    # --- CORS (browser frontend) ---
    # Comma-separated origins allowed to call the API with credentials.
    cors_origins: list[str] = Field(default=["http://localhost:5173", "http://localhost:3000"])

    # --- WildBerries integration ---
    wb_analytics_token: str = Field(default="")
    wb_advertising_token: str = Field(default="")
    wb_analytics_base_url: str = Field(default="https://seller-analytics-api.wildberries.ru")
    wb_advertising_base_url: str = Field(default="https://advert-api.wildberries.ru")
    wb_content_base_url: str = Field(default="https://content-api.wildberries.ru")
    wb_http_timeout_seconds: float = Field(default=30.0)
    # WB (esp. the advertising surface) is aggressively rate-limited (~1 req/min
    # -> HTTP 429). Requests retry with exponential backoff, honouring any
    # Retry-After header. Backoff sequence: base * 2**(attempt-1).
    wb_max_retries: int = Field(default=4)
    wb_retry_backoff_seconds: float = Field(default=2.0)
    wb_retry_max_backoff_seconds: float = Field(default=60.0)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        """Async SQLAlchemy DSN built for the ``asyncpg`` driver."""
        dsn = PostgresDsn.build(
            scheme="postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password,
            host=self.postgres_host,
            port=self.postgres_port,
            path=self.postgres_db,
        )
        return str(dsn)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sync_database_url(self) -> str:
        """Synchronous DSN (psycopg) used by Alembic migrations only."""
        dsn = PostgresDsn.build(
            scheme="postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password,
            host=self.postgres_host,
            port=self.postgres_port,
            path=self.postgres_db,
        )
        return str(dsn)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def redis_url(self) -> str:
        """Redis DSN shared by the Celery broker and result backend."""
        dsn = RedisDsn.build(
            scheme="redis",
            host=self.redis_host,
            port=self.redis_port,
            path=str(self.redis_db),
        )
        return str(dsn)

    @property
    def is_production(self) -> bool:
        """Return ``True`` when running in the production environment."""
        return self.environment == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide cached :class:`Settings` instance.

    The ``lru_cache`` guarantees the environment is parsed exactly once, so the
    same immutable configuration is shared across FastAPI dependencies, Celery
    tasks, and CLI entrypoints.
    """
    return Settings()


settings: Settings = get_settings()
