"""Application configuration loaded from the environment.

Settings are parsed once at import time into a cached ``Settings`` singleton so
that every layer (API process, Celery worker, Alembic) reads an identical,
fully-validated configuration object.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal
from urllib.parse import quote

from pydantic import Field, PostgresDsn, RedisDsn, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "staging", "production"]

#: Placeholder secrets shipped in defaults / ``.env.example``. A production
#: deployment that still carries one of these has forgotten to configure the
#: environment — startup must fail rather than run with a forgeable key.
_PLACEHOLDER_SECRETS: frozenset[str] = frozenset(
    {
        "",
        "change-me",
        "change-me-in-prod",
        "change-me-super-secret-key",
        "insecure-development-key",
        "redis-dev-password",
    }
)


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
    redis_password: str = Field(default="")

    # --- Security / JWT ---
    jwt_secret_key: str = Field(default="insecure-development-key")
    jwt_algorithm: str = Field(default="HS256")
    access_token_ttl_seconds: int = Field(default=900)
    refresh_token_ttl_seconds: int = Field(default=604800)
    # Hard ceiling on one login lineage: rotation slides the 7-day refresh
    # window, but no family may outlive this many seconds from first login.
    session_absolute_lifetime_seconds: int = Field(default=2_592_000)  # 30 days
    refresh_cookie_name: str = Field(default="refresh_token")
    refresh_cookie_secure: bool = Field(default=True)
    # Must match where the auth endpoints are actually mounted so the browser
    # sends the cookie back to /refresh and /logout (they live under /api).
    refresh_cookie_path: str = Field(default="/api/v1/auth")

    # --- Registration & auth abuse protection ---
    # Monitoring data is single-tenant (one seller account), so registration is
    # gated: empty code == registration disabled entirely.
    registration_invite_code: str = Field(default="")
    # Fixed-window per-IP throttle applied to /register, /login and /refresh.
    auth_rate_limit_attempts: int = Field(default=10)
    auth_rate_limit_window_seconds: int = Field(default=60)

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
        return self._postgres_dsn("postgresql+asyncpg")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sync_database_url(self) -> str:
        """Synchronous DSN (psycopg) used by Alembic migrations only."""
        return self._postgres_dsn("postgresql+psycopg")

    def _postgres_dsn(self, scheme: str) -> str:
        """Build a Postgres DSN with URL-encoded credentials.

        ``PostgresDsn.build`` does not percent-encode its inputs, so a rotated
        password containing ``@``, ``:`` or ``/`` would produce an unparseable
        URL and crash every process at import time. Encode defensively.
        """
        dsn = PostgresDsn.build(
            scheme=scheme,
            username=quote(self.postgres_user, safe=""),
            password=quote(self.postgres_password, safe=""),
            host=self.postgres_host,
            port=self.postgres_port,
            path=self.postgres_db,
        )
        return str(dsn)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def redis_url(self) -> str:
        """Redis DSN shared by the Celery broker, result backend, and caches."""
        dsn = RedisDsn.build(
            scheme="redis",
            password=quote(self.redis_password, safe="") or None,
            host=self.redis_host,
            port=self.redis_port,
            path=str(self.redis_db),
        )
        return str(dsn)

    @property
    def is_production(self) -> bool:
        """Return ``True`` when running in the production environment."""
        return self.environment == "production"

    @model_validator(mode="after")
    def _enforce_production_hardening(self) -> Settings:
        """Refuse to start production with placeholder secrets or debug mode.

        A missing/misspelled env var silently falls back to the insecure
        defaults above; in production that means a publicly known HS256 key
        (anyone can forge access tokens) or interactive tracebacks. Failing at
        startup turns a silent compromise into an obvious deploy error.
        """
        if not self.is_production:
            return self

        problems: list[str] = []
        if self.jwt_secret_key in _PLACEHOLDER_SECRETS:
            problems.append("JWT_SECRET_KEY is unset or a known placeholder")
        elif len(self.jwt_secret_key) < 32:
            problems.append("JWT_SECRET_KEY must be at least 32 characters")
        if self.postgres_password in _PLACEHOLDER_SECRETS:
            problems.append("POSTGRES_PASSWORD is unset or a known placeholder")
        if self.redis_password in _PLACEHOLDER_SECRETS:
            problems.append("REDIS_PASSWORD is unset or a known placeholder")
        if self.debug:
            problems.append("DEBUG must be false (leaks tracebacks and SQL echo)")

        if problems:
            raise ValueError(
                "Refusing to start with ENVIRONMENT=production: " + "; ".join(problems) + "."
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide cached :class:`Settings` instance.

    The ``lru_cache`` guarantees the environment is parsed exactly once, so the
    same immutable configuration is shared across FastAPI dependencies, Celery
    tasks, and CLI entrypoints.
    """
    return Settings()


settings: Settings = get_settings()
