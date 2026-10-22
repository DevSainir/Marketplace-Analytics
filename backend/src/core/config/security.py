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

#: The Fernet key ``.env.example`` ships, so a copied template runs the local
#: stack and the demo as it is. A key is needed even with no WB token stored:
#: the refresh-token grace record is encrypted with it too. It decodes to
#: ``local-only-fernet-key-not-secret``, and the line below is what makes that
#: true — every non-local environment refuses to start with it.
LOCAL_FERNET_KEY = "bG9jYWwtb25seS1mZXJuZXQta2V5LW5vdC1zZWNyZXQ="

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
        LOCAL_FERNET_KEY,
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
    # --- Tenancy enforced by the database ---
    # Whether `scripts/sql/row_level_security.sql` has been applied. When true
    # the app binds the caller's workspace to each transaction so the policies
    # can read it; when false that round trip is skipped, because nothing would
    # read the value.
    #
    # ORDER MATTERS, IN ONE DIRECTION ONLY. Turn this ON first and apply the SQL
    # second: binding a setting no policy reads is harmless, whereas policies
    # with nothing binding the setting make every tenant-scoped query RAISE —
    # which is the fail-closed behaviour working as designed, and a total outage
    # if it arrives unannounced.
    #
    # It also only bites once the app has stopped being the table owner
    # (P2.4); until then the policies are inert whatever this says.
    row_level_security_enabled: bool = Field(default=False)

    # --- Diagnostics (see `src/core/diagnostics.py`) ---
    # The workspace a one-off probe against production may read. Empty means the
    # constant in that module — the operator's own — which is what makes the
    # gate work on a box nobody configured. Set it only to point another
    # deployment at its own workspace; it can never widen the gate, because the
    # value is one workspace and there is no "all".
    diagnostic_workspace_id: str = Field(default="")

    # --- Per-tenant resource bounds ---
    # `max_workspaces` / `max_managers` live on the SUBSCRIPTION row, because
    # they are what a customer bought. These three do not: they are safety
    # bounds on shared storage, of the same family as the upload caps in P0.4,
    # and every value below is far above any real use of the product. A tenant
    # that reaches one has stopped using the feature and started filling the
    # database. If any of them ever becomes something a customer *buys*, it
    # moves to the subscription row and stops being a constant.
    #
    # All three are keyed per WORKSPACE rather than per organisation. That is
    # the key the rows actually carry, and since workspaces are already capped
    # per organisation, a per-workspace bound composes into a per-organisation
    # one without a join on every write.
    #
    # One row per SKU. A large seller runs tens of thousands; a hundred
    # thousand is beyond any catalogue we have seen and still bounds a script.
    max_cost_price_rows_per_workspace: int = Field(default=100_000, ge=1)
    # A test is a deliberate, weeks-long thing a human sets up. Hundreds is
    # already generous; thousands means something is generating them.
    max_ab_tests_per_workspace: int = Field(default=500, ge=1)
    # Heatmap groups are named hand-picked sets of articles («спандекс_двойка»).
    # A workspace has tens of product lines at most; a thousand means a script.
    max_sku_groups_per_workspace: int = Field(default=200, ge=1)
    # Comments are bounded by DATE rather than by count, because they carry no
    # workspace column to count against (they are keyed on `nm_id`, which
    # belongs to one seller's catalogue) — and because the bound that matters
    # is meaning, not volume. A note on a day two years out describes nothing;
    # refusing it also caps the rows one SKU can hold at roughly twice this,
    # structurally, with no COUNT on the write path.
    sku_comment_max_days_from_today: int = Field(default=400, ge=1)

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
    # Days of FULL access after a subscription's expiry, before the service
    # closes. Renewal is a manual bank transfer between two humans in two
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
