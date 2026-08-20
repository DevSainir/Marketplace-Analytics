"""The assembled :class:`Settings` object and the process-wide singleton.

The sections in this package each own one area of configuration; this module
is the only place they are composed, and the only place a rule that spans more
than one of them can live. There is exactly one such rule — the startup guard
below, which refuses to boot a deployed environment whose secrets, debug flag
or harvesting mode still carry local defaults.

Nothing imports this module directly: :mod:`src.core.config` re-exports
:class:`Settings`, :func:`get_settings` and :data:`settings` from here.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import SettingsConfigDict

from src.core.config.ab_tests import AbTestsSettings
from src.core.config.app import AppSettings
from src.core.config.datastore import DataStoreSettings
from src.core.config.finreports import FinreportsSettings
from src.core.config.security import PLACEHOLDER_SECRETS, SecuritySettings
from src.core.config.storefront import StorefrontSettings
from src.core.config.wildberries import WildberriesSettings


class Settings(
    AppSettings,
    DataStoreSettings,
    SecuritySettings,
    WildberriesSettings,
    StorefrontSettings,
    FinreportsSettings,
    AbTestsSettings,
):
    """Strongly-typed, validated application settings.

    Every section of this package folded into one object. Values are read from
    environment variables (or a local ``.env`` file) by field name, so which
    section a field is declared in is an organising decision only — it does not
    change the variable that sets it. All fields are explicitly typed to
    satisfy ``mypy --strict`` and to fail fast on a malformed deployment
    configuration.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @model_validator(mode="after")
    def _enforce_production_hardening(self) -> Settings:
        """Refuse to start any non-local environment with placeholder secrets
        or debug mode.

        A missing/misspelled env var silently falls back to the insecure
        default its section carries; on a deployed environment (staging or
        production) that means a publicly known HS256 key (anyone can forge
        access tokens) or interactive tracebacks. Failing at startup turns a
        silent compromise into an obvious deploy error. Only ``local`` is
        exempt.
        """
        if self.environment == "local":
            return self

        problems: list[str] = []
        if self.jwt_secret_key in PLACEHOLDER_SECRETS:
            problems.append("JWT_SECRET_KEY is unset or a known placeholder")
        elif len(self.jwt_secret_key) < 32:
            problems.append("JWT_SECRET_KEY must be at least 32 characters")
        if self.postgres_password in PLACEHOLDER_SECRETS:
            problems.append("POSTGRES_PASSWORD is unset or a known placeholder")
        if self.fernet_secret_key in PLACEHOLDER_SECRETS:
            problems.append("FERNET_SECRET_KEY is unset (required to decrypt workspace WB tokens)")
        if self.redis_password in PLACEHOLDER_SECRETS:
            problems.append("REDIS_PASSWORD is unset or a known placeholder")
        if self.debug:
            problems.append("DEBUG must be false (leaks tracebacks and SQL echo)")
        # Synthetic harvesting fabricates analytics; letting it run anywhere but
        # a developer's own box would silently poison a real seller's numbers.
        if self.wb_fake_harvest:
            problems.append("WB_FAKE_HARVEST must be off (it writes fabricated WB data)")

        if problems:
            raise ValueError(
                f"Refusing to start with ENVIRONMENT={self.environment}: "
                + "; ".join(problems)
                + "."
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
