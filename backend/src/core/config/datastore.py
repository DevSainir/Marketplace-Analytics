"""PostgreSQL and Redis connection settings.

The two stateful backends, kept together because callers never want one
without the other: the API process, the Celery worker and Alembic all read
their DSNs from here, and the DSNs are computed rather than configured so a
rotated password cannot be encoded correctly in one place and wrongly in
another.
"""

from __future__ import annotations

from urllib.parse import quote

from pydantic import Field, PostgresDsn, RedisDsn, computed_field
from pydantic_settings import BaseSettings


class DataStoreSettings(BaseSettings):
    """Postgres and Redis coordinates, plus the DSNs derived from them."""

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
