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

    # --- WildBerries integration ---
    wb_analytics_base_url: str = Field(default="https://seller-analytics-api.wildberries.ru")
    wb_advertising_base_url: str = Field(default="https://advert-api.wildberries.ru")
    wb_content_base_url: str = Field(default="https://content-api.wildberries.ru")
    wb_prices_base_url: str = Field(default="https://discounts-prices-api.wildberries.ru")
    wb_statistics_base_url: str = Field(default="https://statistics-api.wildberries.ru")
    wb_common_base_url: str = Field(default="https://common-api.wildberries.ru")
    # Documents surface: signed weekly-realization / acceptance-act originals
    # (finreports court-grade evidence archival).
    wb_documents_base_url: str = Field(default="https://documents-api.wildberries.ru")
    # Supplies surface: FBW supply / acceptance context (finreports gi_id join).
    wb_supplies_base_url: str = Field(default="https://supplies-api.wildberries.ru")
    # Finance surface: seller balance / settlement (finreports currency context).
    wb_finance_base_url: str = Field(default="https://finance-api.wildberries.ru")
    # Marketplace surface: seller-owned (FBS) warehouses and their stock. Needs
    # a «Маркетплейс»-scope token; no other category authenticates this host.
    wb_marketplace_base_url: str = Field(default="https://marketplace-api.wildberries.ru")
    # The ONE FBS warehouse whose stock is harvested, and the label it shows
    # under in the stock and balance tables.
    #
    # Deliberately a single id rather than a list: the account owns five FBS
    # warehouses but four are test/cross-border stubs holding nothing (verified
    # 2026-08-13), and enabling them would spend rate budget to write zeroes.
    # ``0`` disables FBS harvesting entirely.
    #
    # The label is configured rather than taken from WB because the seller's own
    # warehouse name is a working note («Иван  - Москва (Внуково) НЕ
    # УДАЛЯТЬ!!!») that would become a column header — and because
    # ``warehouse_name`` is a primary-key column, so a rename in the WB portal
    # would otherwise orphan every stored snapshot row and «Отгрузить» mark.
    wb_fbs_warehouse_id: int = Field(default=9945803, ge=0)
    wb_fbs_warehouse_label: str = Field(default="Москва (Внуково) (FBS)")
    # Public storefront card endpoint (card.wb.ru) — the final customer price
    # after ALL discounts incl. WB loyalty (СПП). Unauthenticated. ``dest`` is a
    # region/delivery code and ``spp`` the loyalty tier the storefront prices
    # against; both are fixed inputs the СПП is computed relative to.
    wb_card_base_url: str = Field(default="https://card.wb.ru")
    wb_card_dest: int = Field(default=-1255563)
    wb_card_spp: int = Field(default=30)
    # Optional forward proxy for card.wb.ru ONLY (the other WB surfaces are
    # authenticated seller APIs reached directly). The public storefront edge
    # IP-blocks datacenter egress (prod started getting HTTP 403 on 2026-07-14);
    # a residential/mobile proxy restores the clean egress IP. curl still
    # supplies the TLS fingerprint that clears the anti-bot filter — the proxy
    # only swaps the IP. EMPTY = direct connection (correct for a clean local
    # IP). Holds credentials → lives in .env, never committed.
    wb_card_proxy: str = Field(default="")
    # Strict connect timeout for the (slow, fragile) proxy tunnel — separate
    # from the whole-request cap so a dead tunnel fails fast instead of burning
    # the full timeout budget (bounds proxy traffic/cost on failure).
    wb_card_connect_timeout_seconds: float = Field(default=15.0)
    # Tighter retry cap than the rate-limited seller APIs: a broken proxy must
    # give up quickly instead of spinning (protects the proxy balance).
    wb_card_max_retries: int = Field(default=3)
    # Public storefront SEARCH endpoint (search.wb.ru) — the organic ranking a
    # shopper sees, which no seller API exposes. Unauthenticated, shares the
    # card endpoint's anti-bot edge, its proxy and its timeout/retry budget.
    wb_search_base_url: str = Field(default="https://search.wb.ru")
    # The API version is a knob because WB retires them abruptly: verified live
    # 2026-08-14, v14 served results while v13 and v5 answered 429 to every
    # request from the same IP in the same minute.
    wb_search_path: str = Field(default="/exactmatch/ru/common/v14/search")
    # Delivery region the ranking is computed for (see wb_card_dest). A position
    # is only meaningful together with this value.
    wb_search_dest: int = Field(default=-1257786)
    # Result slots per page; 100 is what the storefront itself requests.
    wb_search_page_size: int = Field(default=100, ge=1, le=300)
    # How deep a position probe may scan. Pages are fetched SEQUENTIALLY because
    # the host 429s back-to-back requests, so this bounds the endpoint's latency
    # as much as WB's patience: 3 pages = the top 300 positions.
    wb_search_max_pages: int = Field(default=3, ge=1, le=20)
    # How long a keyword's probe result is reused (Redis). The ranking moves
    # within the hour, so this trades freshness for not being throttled: a team
    # of five checking the same phrase pays for one probe.
    wb_search_cache_seconds: int = Field(default=600, ge=0)
    # Relative paths resolve against the backend working directory.
    # disables caching entirely. Relative paths resolve against the backend
    # working directory; a bind mount or S3 can replace it without code changes.
    # How many built packages to keep. Each is a few MB, and a full disk on this
    # box has taken the API down before, so the oldest are pruned.
    finreports_package_cache_entries: int = Field(default=24, ge=1)
    # .cache), keyed by a content digest of its inputs. The entry is only a
    # cost saver — correctness comes from the digest, not the clock — so the TTL
    # just bounds Redis growth for windows that stop being asked for. 0 disables
    # caching entirely.
    finreports_summary_cache_ttl_seconds: int = Field(default=1209600, ge=0)
    # Fake WB harvesting for LOCAL development. When on, the harvest tasks build
    # synthetic WB clients instead of the real HTTP ones (see
    # ``src.integrations.wildberries.build_*_client``): no request ever leaves
    # the box, and deterministic, plausible rows are written to the real tables
    # so the UI and pipeline stay debuggable without burning WB's rate budget.
    #
    # The code path is IDENTICAL to production — only this flag differs — so
    # local and prod never diverge. It is refused outright on any non-local
    # environment (see ``_enforce_production_hardening``): fabricated analytics
    # must never reach a real seller's dashboard, so prod cannot even boot with
    # it on. EMPTY/false everywhere but a developer's own ``.env``.
    wb_fake_harvest: bool = Field(default=False)
    wb_http_timeout_seconds: float = Field(default=30.0)
    # WB (esp. the advertising surface) is aggressively rate-limited (~1 req/min
    # -> HTTP 429). Requests retry with exponential backoff, honouring any
    # Retry-After header. Backoff sequence: base * 2**(attempt-1).
    wb_max_retries: int = Field(default=4)
    wb_retry_backoff_seconds: float = Field(default=2.0)
    wb_retry_max_backoff_seconds: float = Field(default=60.0)
    # Client-side pacing of the analytics surface, measured live on 2026-07-30
    # against seller-analytics-api: each endpoint holds a 3-token bucket per
    # seller token and refills one token within 20s (a call every 20s keeps
    # ``x-ratelimit-remaining`` pinned at 2; a call 5s later drops it to 1).
    # Overrunning it does NOT reliably answer 429 — WB returns HTTP 500, or
    # holds the connection until our read timeout — so the budget has to be
    # respected before sending, not discovered afterwards.
    wb_analytics_bucket_capacity: int = Field(default=3, ge=1)
    wb_analytics_bucket_refill_seconds: float = Field(default=20.0, gt=0)
    # A request may queue this long for a token before the client gives up. The
    # 22-day cohort pass needs ~7 min of queueing overall but never more than
    # one refill per call; anything beyond this means the budget is being
    # consumed faster than it refills, and failing lets the task's retry policy
    # reschedule instead of parking a worker.
    wb_analytics_max_queue_seconds: float = Field(default=120.0, gt=0)
    # The marketplace (FBS) surface answered ``x-ratelimit-remaining: 20`` on
    # both its endpoints when measured live on 2026-08-13. Refill is assumed
    # per-minute (WB publishes no window); the header clamp corrects us
    # downward on every response, so guessing generously here is safe.
    wb_marketplace_bucket_capacity: int = Field(default=20, ge=1)
    wb_marketplace_bucket_refill_seconds: float = Field(default=3.0, gt=0)
    # Escape hatch: disables Redis-backed pacing (tests and any environment
    # with no Redis). The clients then fall back to per-process spacing.
    wb_rate_pacing_enabled: bool = Field(default=True)

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
        """Refuse to start any non-local environment with placeholder secrets
        or debug mode.

        A missing/misspelled env var silently falls back to the insecure
        defaults above; on a deployed environment (staging or production) that
        means a publicly known HS256 key (anyone can forge access tokens) or
        interactive tracebacks. Failing at startup turns a silent compromise
        into an obvious deploy error. Only ``local`` is exempt.
        """
        if self.environment == "local":
            return self

        problems: list[str] = []
        if self.jwt_secret_key in _PLACEHOLDER_SECRETS:
            problems.append("JWT_SECRET_KEY is unset or a known placeholder")
        elif len(self.jwt_secret_key) < 32:
            problems.append("JWT_SECRET_KEY must be at least 32 characters")
        if self.postgres_password in _PLACEHOLDER_SECRETS:
            problems.append("POSTGRES_PASSWORD is unset or a known placeholder")
        if self.fernet_secret_key in _PLACEHOLDER_SECRETS:
            problems.append("FERNET_SECRET_KEY is unset (required to decrypt workspace WB tokens)")
        if self.redis_password in _PLACEHOLDER_SECRETS:
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
