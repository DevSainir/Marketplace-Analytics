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
    # Registration is OPEN: anyone may create an account, and a bare account can
    # reach nothing at all (no organisation, no workspaces, no data). Access is
    # granted afterwards — by redeeming an activation code, which makes the
    # holder an owner, or by accepting an owner's invitation, which makes them a
    # manager. See src/modules/organizations.
    # Fixed-window per-IP throttle applied to /register and /login (guessable
    # secrets: passwords, invite codes).
    auth_rate_limit_attempts: int = Field(default=10)
    auth_rate_limit_window_seconds: int = Field(default=60)
    # Refuse passwords that are already public, via Have I Been Pwned's range
    # API. Only the first five characters of the candidate's SHA-1 leave this
    # process (k-anonymity) — see src/integrations/pwned.py. Off makes the
    # check a no-op rather than an error, which is how the test tiers stay
    # hermetic and how the feature is switched off if HIBP ever goes away.
    password_breach_check_enabled: bool = Field(default=True)
    # Short on purpose: this sits in the registration path, so a slow third
    # party must not become a slow signup form. Exceeding it allows the
    # password, like every other failure of this check.
    password_breach_check_timeout_seconds: float = Field(default=2.0)
    # /refresh gets its OWN budget: its secret is an unguessable 256-bit cookie
    # (throttling is abuse damping, not brute-force defense), and every page
    # load fires a silent refresh — sharing the tight login budget bounced
    # legitimate sessions to /login whenever the window was exhausted.
    refresh_rate_limit_attempts: int = Field(default=60)
    # How long after a refresh token is consumed its replacement is still served
    # to another presenter of it. Three tabs share one cookie jar and each fires
    # /refresh on page load: without this the first rotates and the other two
    # look exactly like a replayed stolen token, so the family is revoked and a
    # working user is signed out. 30 s covers the tab race and a client-side
    # timeout retry, and is far short of the days-later replay that is the case
    # actually worth revoking a family over.
    refresh_replay_grace_seconds: int = Field(default=30)
    # Per-WORKSPACE budget on enqueueing WB re-harvests («Обновить»). Keyed on
    # the tenant rather than the address because that is who spends the queue
    # and the WB rate budget behind it: one account on one IP can hold several
    # workspaces, and one workspace is reachable from every device its members
    # own. 20 per 5 minutes is far above any human use of the button (four a
    # minute, sustained) and still bounds what a script can pile onto a worker
    # pool of four.
    refresh_enqueue_attempts: int = Field(default=20)
    refresh_enqueue_window_seconds: int = Field(default=300)
    # How long an identical refresh request is answered with the task already in
    # flight instead of a second one. Covers the double-click and the impatient
    # re-click; short enough that a genuine retry after a failed harvest is not
    # blocked for long.
    refresh_dedup_window_seconds: int = Field(default=120)

    # --- CORS (browser frontend) ---
    # In production the SPA is served by nginx on the SAME origin as the API
    # (/api/ reverse proxy), so cross-origin requests never happen and the
    # middleware is disabled (CORS_ENABLED=false). Locally the Vite dev server
    # may still call the API cross-origin, so it stays enabled by default.
    cors_enabled: bool = Field(default=True)
    # Comma-separated origins allowed to call the API with credentials.
    cors_origins: list[str] = Field(default=["http://localhost:5173", "http://localhost:3000"])

    # --- Subscriptions ---
    # Days of FULL access after a subscription's expiry, before it drops to
    # read-only. Renewal is a manual bank transfer between two humans in two
    # countries, and the failure this prevents — a seller locked out of their
    # own numbers on the morning their payment is still clearing — is far worse
    # than a few extra days of access. Stored per subscription so one customer
    # can be given more without a deploy; this is only the default at creation.
    subscription_grace_days: int = Field(default=3, ge=0)

    # --- Workspace token encryption ---
    # Fernet key encrypting per-workspace WB API tokens at rest
    # (workspaces.workspace_tokens). WB tokens no longer live in the
    # environment — they are stored encrypted in the database, one set per
    # workspace. Generate with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    fernet_secret_key: str = Field(default="")
