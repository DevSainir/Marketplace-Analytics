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
from src.core.config.email import EmailSettings
from src.core.config.finreports import FinreportsSettings
from src.core.config.guide import GuideSettings
from src.core.config.observability import ObservabilitySettings
from src.core.config.security import PLACEHOLDER_SECRETS, SecuritySettings
from src.core.config.storefront import StorefrontSettings
from src.core.config.wildberries import WildberriesSettings


class Settings(
    AppSettings,
    DataStoreSettings,
    SecuritySettings,
    EmailSettings,
    WildberriesSettings,
    StorefrontSettings,
    FinreportsSettings,
    GuideSettings,
    AbTestsSettings,
    ObservabilitySettings,
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

        # Not a "problem" — a default that is only right for a human at a
        # terminal. A deployed environment is read by a shipper, and the human
        # format is where a user-controlled value could pretend to be a field
        # (P2.2). Set rather than refused, because failing a deploy over a log
        # format would be a worse trade than quietly getting it right.
        self.log_json = True

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
        # nginx serves the SPA and the API from the SAME origin on every
        # deployment, so a deployed environment has no legitimate cross-origin
        # caller — and CORS is what decides whether somebody else's page may
        # read our authenticated responses. Register P0.7 verified this was off
        # in production by reading the deployed `.env`; nothing made it STAY
        # off, and the default is `true`, so one dropped line would have
        # re-enabled it silently. Refused rather than forced quietly, matching
        # DEBUG above: a security control that corrects itself teaches nobody,
        # and this is one line in a file.
        if self.cors_enabled:
            problems.append(
                "CORS_ENABLED must be false (the SPA and API are same-origin behind nginx)"
            )
        # The refresh token is the long-lived half of the session — the one an
        # access token is minted from for a week. Without `Secure` a browser
        # will send it over plain HTTP, which is the entire threat HSTS and the
        # 301 exist to remove. The default is already `true`, so this catches an
        # active misconfiguration rather than an omission; it is cheap, and the
        # failure it prevents is silent (the cookie still works, it is just no
        # longer confined to TLS).
        if not self.refresh_cookie_secure:
            problems.append(
                "REFRESH_COOKIE_SECURE must be true (the refresh token would travel in clear)"
            )
        # Synthetic harvesting fabricates analytics; letting it run anywhere but
        # a developer's own box would silently poison a real seller's numbers.
        if self.wb_fake_harvest:
            problems.append("WB_FAKE_HARVEST must be off (it writes fabricated WB data)")
        # A flow that needs mail, on a deployment that cannot send it, fails at
        # the registration form rather than at the thing that is broken — and
        # the people who see it are the ones with no way to report it. Refuse
        # the combination outright (register P1.6).
        problems.extend(self._email_configuration_problems())

        if problems:
            raise ValueError(
                f"Refusing to start with ENVIRONMENT={self.environment}: "
                + "; ".join(problems)
                + "."
            )
        return self

    def _email_configuration_problems(self) -> list[str]:
        """Return the ways this deployment's mail settings contradict themselves.

        Split out because it is a different kind of check from the ones above:
        those refuse a placeholder secret, this refuses an *incoherent* pair of
        settings. Both fail the boot, which is the point — a deploy error is
        cheap and a signup form that silently cannot complete is not.

        Returns:
            Human-readable problems, empty when the configuration is coherent.
        """
        problems: list[str] = []
        needs_mail = self.email_confirmation_required or self.password_reset_enabled
        if needs_mail and not self.email_enabled:
            problems.append(
                "EMAIL_CONFIRMATION_REQUIRED/PASSWORD_RESET_ENABLED need EMAIL_ENABLED=true "
                "(a flow that sends no mail cannot be completed by anyone)"
            )
        if self.email_enabled:
            if not self.smtp_host:
                problems.append("SMTP_HOST is required when EMAIL_ENABLED=true")
            if not self.email_from:
                problems.append("EMAIL_FROM is required when EMAIL_ENABLED=true")
            if not self.smtp_use_tls:
                problems.append(
                    "SMTP_USE_TLS must be true outside local: plaintext SMTP hands every "
                    "reset code to anyone on the path"
                )
        return problems


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide cached :class:`Settings` instance.

    The ``lru_cache`` guarantees the environment is parsed exactly once, so the
    same immutable configuration is shared across FastAPI dependencies, Celery
    tasks, and CLI entrypoints.
    """
    return Settings()


settings: Settings = get_settings()
