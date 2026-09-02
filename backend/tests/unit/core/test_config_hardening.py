"""Unit tests for the production-hardening startup guard.

A missing environment variable silently falls back to the insecure default
baked into :class:`Settings` — a publicly known HS256 key, an empty Fernet key,
``redis-dev-password``. On a deployed environment that is a silent compromise,
so :class:`Settings` refuses to construct. These tests pin *which* mistakes are
fatal and confirm ``local`` stays exempt, since forcing every developer to
generate four secrets before running the app would push people back to ``.env``
files copied between machines.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from src.core.config import Settings

#: A configuration that passes every hardening check, used as the base for
#: single-field mutations below.
_SECURE_ENV: dict[str, str] = {
    "ENVIRONMENT": "production",
    "DEBUG": "false",
    "JWT_SECRET_KEY": "x" * 48,
    "POSTGRES_PASSWORD": "a-real-generated-password",
    "REDIS_PASSWORD": "another-real-password",
    "FERNET_SECRET_KEY": Fernet.generate_key().decode(),
}


def _settings(env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Construct :class:`Settings` from an explicit environment.

    ``_env_file=None`` keeps ``backend/.env`` from leaking real local values
    into the assertion — the point is what *this* environment produces.
    """
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_fully_configured_production_starts(monkeypatch: pytest.MonkeyPatch) -> None:
    """A production environment with real secrets constructs successfully."""
    settings = _settings(_SECURE_ENV, monkeypatch)

    assert settings.is_production is True


def test_local_environment_tolerates_placeholder_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``local`` is exempt: developers must be able to just run the app."""
    settings = _settings({"ENVIRONMENT": "local", "JWT_SECRET_KEY": "change-me"}, monkeypatch)

    assert settings.is_production is False


@pytest.mark.parametrize(
    ("field", "value", "expected_message"),
    [
        ("JWT_SECRET_KEY", "change-me-super-secret-key", "JWT_SECRET_KEY"),
        ("JWT_SECRET_KEY", "too-short", "at least 32 characters"),
        ("POSTGRES_PASSWORD", "change-me-in-prod", "POSTGRES_PASSWORD"),
        ("REDIS_PASSWORD", "redis-dev-password", "REDIS_PASSWORD"),
        ("FERNET_SECRET_KEY", "", "FERNET_SECRET_KEY"),
        ("DEBUG", "true", "DEBUG must be false"),
        ("WB_FAKE_HARVEST", "true", "WB_FAKE_HARVEST"),
    ],
)
def test_production_refuses_each_insecure_default(
    field: str,
    value: str,
    expected_message: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every individually insecure production setting aborts startup."""
    env = {**_SECURE_ENV, field: value}

    with pytest.raises(ValueError, match=expected_message):
        _settings(env, monkeypatch)


def test_local_allows_fake_harvesting(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fake WB harvesting is a local-only convenience and is accepted there.

    It swaps the real WB clients for synthetic ones so local dev stops spending
    WB's rate budget; the value must actually read back as ``True`` so the
    factory seam takes the synthetic branch.
    """
    settings = _settings({"ENVIRONMENT": "local", "WB_FAKE_HARVEST": "true"}, monkeypatch)

    assert settings.wb_fake_harvest is True


def test_production_refuses_fake_harvesting(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fake harvesting cannot boot outside local: it fabricates analytics.

    Letting it run on a deployed environment would silently write invented
    numbers onto a real seller's dashboard, so the guard refuses startup rather
    than trusting the flag to be off by luck.
    """
    env = {**_SECURE_ENV, "WB_FAKE_HARVEST": "true"}

    with pytest.raises(ValueError, match="WB_FAKE_HARVEST"):
        _settings(env, monkeypatch)


def test_staging_is_hardened_like_production(monkeypatch: pytest.MonkeyPatch) -> None:
    """Staging is internet-reachable too, so it gets the same guard."""
    env = {**_SECURE_ENV, "ENVIRONMENT": "staging", "JWT_SECRET_KEY": "insecure-development-key"}

    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        _settings(env, monkeypatch)


def test_only_local_may_publish_its_own_api_surface(monkeypatch: pytest.MonkeyPatch) -> None:
    """Interactive docs are a development affordance, not a deployed feature.

    ``/openapi.json`` is the complete route inventory with every schema and
    parameter. The SPA is written against the API and never reads it, so on any
    reachable deployment it is reconnaissance served for free.
    """
    deployed = _settings({**_SECURE_ENV, "ENVIRONMENT": "production"}, monkeypatch)

    assert deployed.api_docs_enabled is False


def test_a_deployed_environment_logs_json_whatever_the_env_says(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The format is a deployed fact, not an operator preference.

    A deployed log is read by a shipper, and structure carried by an encoder
    rather than by punctuation is what stops a user-controlled value — a path,
    an email, an upstream error — pretending to be a field (register P2.2).
    Left to a default it would be one forgotten `.env` line away from silently
    reverting, so the environment decides rather than the file.

    Set rather than refused: failing a deploy over a log format would be the
    worse trade.
    """
    deployed = _settings(
        {**_SECURE_ENV, "ENVIRONMENT": "production", "LOG_JSON": "false"}, monkeypatch
    )

    assert deployed.log_json is True


def test_local_keeps_the_human_log_format(monkeypatch: pytest.MonkeyPatch) -> None:
    """A person at a terminal wants columns, not braces."""
    local = _settings({**_SECURE_ENV, "ENVIRONMENT": "local"}, monkeypatch)

    assert local.log_json is False


def test_staging_withholds_the_docs_like_production(monkeypatch: pytest.MonkeyPatch) -> None:
    """The switch is ``local``, not ``is_production`` — staging is reachable too.

    Keying this on :attr:`is_production` would have left staging publishing the
    whole schema, which is the same disclosure from a box that is usually less
    watched.
    """
    env = {**_SECURE_ENV, "ENVIRONMENT": "staging"}

    assert _settings(env, monkeypatch).api_docs_enabled is False


def test_local_development_keeps_the_docs(monkeypatch: pytest.MonkeyPatch) -> None:
    """A developer's own box still gets Swagger; nothing is reachable from it."""
    local = _settings({"ENVIRONMENT": "local"}, monkeypatch)

    assert local.api_docs_enabled is True


def test_all_problems_are_reported_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """A misconfigured deploy lists every fault, not just the first.

    Reporting one problem per restart turns a five-minute fix into five deploy
    cycles.
    """
    env = {
        **_SECURE_ENV,
        "JWT_SECRET_KEY": "change-me",
        "REDIS_PASSWORD": "redis-dev-password",
        "DEBUG": "true",
    }

    with pytest.raises(ValueError, match="Refusing to start") as excinfo:
        _settings(env, monkeypatch)

    message = str(excinfo.value)
    assert "JWT_SECRET_KEY" in message
    assert "REDIS_PASSWORD" in message
    assert "DEBUG" in message


def test_dsn_encodes_credentials_with_url_unsafe_characters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rotated password containing ``@``/``:``/``/`` must not corrupt the DSN.

    ``PostgresDsn.build`` does not percent-encode, so an unescaped password
    would produce an unparseable URL and crash every process at import time —
    API, worker and Alembic at once.
    """
    env = {**_SECURE_ENV, "POSTGRES_PASSWORD": "p@ss:w/rd", "POSTGRES_HOST": "db.internal"}

    settings = _settings(env, monkeypatch)

    assert "p%40ss%3Aw%2Frd" in settings.database_url
    assert settings.database_url.startswith("postgresql+asyncpg://")
    assert settings.sync_database_url.startswith("postgresql+psycopg://")
    assert "@db.internal" in settings.database_url


def test_redis_url_carries_the_password_and_db_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Broker and cache share one DSN; a dropped password means an open Redis.

    An unauthenticated Redis reachable as the Celery broker is remote code
    execution, so the password must survive DSN assembly.
    """
    env = {**_SECURE_ENV, "REDIS_PASSWORD": "s3cr#t", "REDIS_DB": "3"}

    settings = _settings(env, monkeypatch)

    assert "s3cr%23t" in settings.redis_url
    assert settings.redis_url.endswith("/3")


# --------------------------------------------------------------------------- #
# Mail configuration (register P1.6)
#
# A different kind of check from the ones above: those refuse a placeholder
# secret, these refuse an *incoherent pair*. Both fail the boot, and for the
# same reason — a deploy error is cheap, and a signup form that silently cannot
# be completed is not. The people who hit that failure are the ones with no way
# to report it.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("overrides", "case"),
    [
        ({"PASSWORD_RESET_ENABLED": "true"}, "reset without a transport"),
        ({"EMAIL_CONFIRMATION_REQUIRED": "true"}, "confirmation without a transport"),
        ({"EMAIL_ENABLED": "true"}, "transport without a host"),
        (
            {"EMAIL_ENABLED": "true", "SMTP_HOST": "smtp.example.com"},
            "transport without a from-address",
        ),
        (
            {
                "EMAIL_ENABLED": "true",
                "SMTP_HOST": "smtp.example.com",
                "EMAIL_FROM": "no-reply@example.com",
                "SMTP_USE_TLS": "false",
            },
            "plaintext SMTP, which hands every reset code to the path",
        ),
    ],
    ids=["reset-no-transport", "confirm-no-transport", "no-host", "no-from", "no-tls"],
)
def test_an_incoherent_mail_configuration_refuses_to_boot(
    overrides: dict[str, str], case: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each of these would deploy a flow that cannot work, or works insecurely."""
    with pytest.raises(ValueError, match="Refusing to start"):
        _settings({**_SECURE_ENV, **overrides}, monkeypatch)


def test_a_fully_configured_mail_setup_boots(monkeypatch: pytest.MonkeyPatch) -> None:
    """The guard must not be so eager that a correct configuration cannot ship."""
    settings = _settings(
        {
            **_SECURE_ENV,
            "EMAIL_ENABLED": "true",
            "SMTP_HOST": "smtp.example.com",
            "EMAIL_FROM": "no-reply@example.com",
            "PASSWORD_RESET_ENABLED": "true",
            "EMAIL_CONFIRMATION_REQUIRED": "true",
        },
        monkeypatch,
    )

    assert settings.email_enabled is True


def test_mail_switched_off_entirely_boots(monkeypatch: pytest.MonkeyPatch) -> None:
    """The shipped default: no relay, no flows, and a production boot regardless.

    This is what the deploy that introduced P1.6 actually ran, so it is the case
    that must never regress into a refusal — the feature ships dark on purpose.
    """
    settings = _settings({**_SECURE_ENV, "EMAIL_ENABLED": "false"}, monkeypatch)

    assert settings.email_enabled is False
    assert settings.password_reset_enabled is False
    assert settings.email_confirmation_required is False
