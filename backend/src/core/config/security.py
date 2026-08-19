"""Authentication, session and browser-facing security settings.

Everything that decides who may talk to the API and with what: the JWT signing
key and token lifetimes, the refresh cookie, the abuse throttles on the
guessable-secret endpoints, the CORS allowance, and the Fernet key that
encrypts per-workspace WB tokens at rest.

:data:`PLACEHOLDER_SECRETS` lists the values that mean "nobody configured
this"; the startup guard in :mod:`src.core.config.assembly` refuses to boot a
deployed environment carrying one.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings

#: Placeholder secrets shipped in defaults / ``.env.example``. A production
#: deployment that still carries one of these has forgotten to configure the
#: environment — startup must fail rather than run with a forgeable key.
PLACEHOLDER_SECRETS: frozenset[str] = frozenset(
    {
        "",
        "change-me",
        "change-me-in-prod",
        "change-me-super-secret-key",
        "insecure-development-key",
        "redis-dev-password",
    }
)


class SecuritySettings(BaseSettings):
    """JWT, session cookie, registration, throttling, CORS and encryption."""

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
    # Fixed-window per-IP throttle applied to /register and /login (guessable
    # secrets: passwords, invite codes).
    auth_rate_limit_attempts: int = Field(default=10)
    auth_rate_limit_window_seconds: int = Field(default=60)
    # /refresh gets its OWN budget: its secret is an unguessable 256-bit cookie
    # (throttling is abuse damping, not brute-force defense), and every page
    # load fires a silent refresh — sharing the tight login budget bounced
    # legitimate sessions to /login whenever the window was exhausted.
    refresh_rate_limit_attempts: int = Field(default=60)

    # --- CORS (browser frontend) ---
    # In production the SPA is served by nginx on the SAME origin as the API
    # (/api/ reverse proxy), so cross-origin requests never happen and the
    # middleware is disabled (CORS_ENABLED=false). Locally the Vite dev server
    # may still call the API cross-origin, so it stays enabled by default.
    cors_enabled: bool = Field(default=True)
    # Comma-separated origins allowed to call the API with credentials.
    cors_origins: list[str] = Field(default=["http://localhost:5173", "http://localhost:3000"])

    # --- Workspace token encryption ---
    # Fernet key encrypting per-workspace WB API tokens at rest
    # (workspaces.workspace_tokens). WB tokens no longer live in the
    # environment — they are stored encrypted in the database, one set per
    # workspace. Generate with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    fernet_secret_key: str = Field(default="")
