"""FastAPI application entrypoint for the Marketplace Service.

Wires the module routers into a single ASGI app, installs a global exception
handler that maps semantic :class:`AppError` domain errors onto HTTP responses,
and manages the async engine lifecycle. Run with::

    uvicorn main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import NamedTuple

from fastapi import FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.core.client_ip import resolve_client_ip
from src.core.config import settings
from src.core.database import dispose_engine
from src.core.exceptions import AppError
from src.core.logcontext import bind_request, new_request_id, reset_context
from src.core.logging import adopt_uvicorn_loggers, configure_logging, get_logger
from src.core.observability.instrument import instrument_app, register_observability_routes
from src.core.observability.metrics import set_app_info
from src.core.observability.sentry import configure_sentry
from src.core.redis import close_redis
from src.modules.ab_tests.deps import close_media_store
from src.modules.ab_tests.routers import router as ab_tests_router
from src.modules.finreports.routers import router as finreports_router
from src.modules.monitoring.routers import router as monitoring_router
from src.modules.organizations.routers import router as organizations_router
from src.modules.summary.routers import router as summary_router
from src.modules.users.routers import router as users_router
from src.modules.workspaces.routers import router as workspaces_router

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup and shutdown.

    Configures logging on startup; disposes of the async engine's connection
    pool, the shared Redis client and the A/Б media client on shutdown so the
    process exits cleanly.
    """
    configure_logging()
    # After uvicorn has installed its own handlers, and before anything it logs
    # about a failing startup — see the function's docstring.
    adopt_uvicorn_loggers()
    # Reporting on before the first request, so a failure during startup is
    # itself reported. `configure_sentry` says which of the two happened,
    # because "Sentry disabled" in the boot log is the fact worth having on
    # the day errors do not appear in it.
    reporting = configure_sentry(component="api")
    set_app_info(version=app.version, environment=settings.environment, component="api")
    logger.info(
        "Starting %s (env=%s, error reporting %s).",
        settings.app_name,
        settings.environment,
        "on" if reporting else "off",
    )
    yield
    await dispose_engine()
    await close_redis()
    # The A/Б media store holds one S3 connection open for the life of this
    # loop — that is what stops nine photos on one page from paying nine TLS
    # handshakes. This is the only place that knows the loop is ending.
    await close_media_store()
    logger.info("Shutdown complete; database engine, Redis and media clients disposed.")


class DocumentationUrls(NamedTuple):
    """Where (or whether) FastAPI mounts its own documentation."""

    docs_url: str | None
    redoc_url: str | None
    openapi_url: str | None


def documentation_urls(*, enabled: bool) -> DocumentationUrls:
    """Return the interactive-documentation URLs FastAPI should mount.

    The three move together on purpose. Turning off ``/docs`` and ``/redoc``
    while leaving ``/openapi.json`` is the usual half-fix, and it withholds
    nothing: the schema *is* the route inventory, and the two viewers are only
    renderers of it. ``None`` unmounts the route rather than hiding it, so there
    is nothing left to reach.

    Args:
        enabled: Whether this environment may publish its own API surface.

    Returns:
        The three URLs, or all ``None`` when the documentation is withheld.
    """
    if not enabled:
        return DocumentationUrls(None, None, None)
    return DocumentationUrls("/docs", "/redoc", "/openapi.json")


_documentation = documentation_urls(enabled=settings.api_docs_enabled)

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    default_response_class=JSONResponse,
    debug=settings.debug,
    lifespan=lifespan,
    docs_url=_documentation.docs_url,
    redoc_url=_documentation.redoc_url,
    openapi_url=_documentation.openapi_url,
)

# HTTP metrics middleware, added before the app starts serving. Its own
# exposition route and the readiness probe are mounted further down, next to
# the liveness probe they are easy to confuse with.
instrument_app(app)

# CORS for the browser frontend. ``allow_credentials`` is required so the
# HttpOnly refresh cookie is accepted; it forbids the ``*`` origin wildcard, so
# explicit origins are configured via settings. In production the nginx
# reverse proxy serves the SPA and the API from one origin, so the middleware
# is switched off entirely via CORS_ENABLED=false.
if settings.cors_enabled:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


#: Paths whose requests are neither logged nor counted. Kept beside the
#: middleware that skips them and mirrored by `_EXCLUDED` in
#: `src.core.observability.instrument`, which excludes the same three from the
#: HTTP metrics for the same reason.
_UNLOGGED_PATHS: frozenset[str] = frozenset({"/health", "/healthz", settings.metrics_path})


@app.middleware("http")
async def log_requests(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Emit one line per request, and bind the context every other line uses.

    Uvicorn's access log is silenced by :mod:`src.core.logging`; without this
    middleware the API would have no record of who called what. The liveness
    probe is skipped to keep orchestrator polling out of the logs.

    **The binding matters more than the line.** Everything this request goes on
    to log — a rate-limit trip, a revoked session, a WB failure deep in a
    service — is attributed to this request id, this address and (once the auth
    dependency resolves them) this account and tenant, without any of those call
    sites knowing that logging context exists (register P2.2).

    The id is returned as ``X-Request-Id`` so a customer reporting "it failed at
    about two" can hand over the one string that finds it.
    """
    # Three paths are polled forever by machines — Docker's healthcheck, Better
    # Stack, and Prometheus — so logging them would make the request log mostly
    # a record of the monitoring watching the service.
    if request.url.path in _UNLOGGED_PATHS:
        return await call_next(request)
    request_id = new_request_id()
    # The address nginx wrote, never one the caller chose — see P0.1.
    bind_request(
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        client_ip=resolve_client_ip(request),
    )
    started = time.perf_counter()
    try:
        response = await call_next(request)
        duration_ms = (time.perf_counter() - started) * 1000
        # `extra` rather than an interpolated string: the fields stay fields, so
        # an alert can bind to `status` instead of parsing prose.
        logger.info(
            "request served",
            extra={"status": response.status_code, "duration_ms": round(duration_ms, 1)},
        )
        response.headers["X-Request-Id"] = request_id
        return response
    finally:
        # A worker serves the next request on the same task context; a value
        # left bound would attribute it to this caller, and a wrong answer is
        # worse than no answer.
        reset_context()


@app.exception_handler(AppError)
async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    """Translate any uncaught domain :class:`AppError` into an HTTP response.

    This is the single place where escaped business errors become transport
    responses, keeping services free of HTTP concerns.

    Args:
        request: The incoming request (used for logging context).
        exc: The raised domain error carrying a code and suggested status.

    Returns:
        A JSON error envelope with the mapped HTTP status code.
    """
    # Severity follows the status, not the exception's class. A 4xx is the
    # client being told "no" and belongs at INFO; a 5xx — an IntegrationError
    # from WB, or any AppError that reached here without a mapped status — is
    # OUR failure and has to survive a WARNING-level log scrape, which is what
    # a uniform INFO used to hide.
    log = logger.info if exc.http_status < 500 else logger.warning
    log(
        "Domain error on %s %s: %s (%d) %s",
        request.method,
        request.url.path,
        exc.code,
        exc.http_status,
        # The detail belongs HERE and only here. It used to travel the other way
        # round — withheld from the log, returned to the client — so a WB
        # failure answered the browser with upstream text and left the operator
        # with a bare error code.
        exc.message,
    )
    return JSONResponse(
        status_code=exc.http_status,
        content={"error": {"code": exc.code, "message": exc.public_message}},
    )


#: Pydantic's own ``msg`` is English prose ("String should have at least 8
#: characters"), and `extractErrorMessage` in the SPA puts it straight in front
#: of the user. Mapped by error TYPE rather than by matching on its text, which
#: is not a stable interface.
#:
#: Only ``ctx`` limits are interpolated — ``min_length`` and friends are
#: constants from our own schema, never the submitted value. That distinction
#: is the whole reason `handle_validation_error` drops ``input`` and ``ctx``
#: from the response: a rejected password must not come back in the body.
_RU_VALIDATION: dict[str, str] = {
    "missing": "Обязательное поле.",
    "string_too_short": "Слишком короткое значение — минимум {min_length}.",
    "string_too_long": "Слишком длинное значение — максимум {max_length}.",
    "string_pattern_mismatch": "Значение имеет недопустимый формат.",
    "value_error": "Некорректное значение.",
    "int_parsing": "Ожидается целое число.",
    "float_parsing": "Ожидается число.",
    "bool_parsing": "Ожидается «да» или «нет».",
    "datetime_parsing": "Некорректная дата.",
    "date_parsing": "Некорректная дата.",
    "uuid_parsing": "Некорректный идентификатор.",
    "enum": "Недопустимое значение.",
    "greater_than": "Значение должно быть больше {gt}.",
    "greater_than_equal": "Значение должно быть не меньше {ge}.",
    "less_than": "Значение должно быть меньше {lt}.",
    "less_than_equal": "Значение должно быть не больше {le}.",
    "too_short": "Слишком мало элементов.",
    "too_long": "Слишком много элементов.",
    "json_invalid": "Тело запроса не является корректным JSON.",
}


def _russian_validation_message(error: dict[str, object]) -> str:
    """Render one Pydantic error in Russian.

    Args:
        error: One entry from ``RequestValidationError.errors()``.

    Returns:
        A Russian sentence. Falls back to a generic one for any error type not
        listed — a type we have not seen is still not an excuse to show English.
    """
    kind = str(error.get("type", ""))
    # A `value_error` is the one type that can already be OURS: a
    # `field_validator` raising `ValueError` lands here, and this codebase's
    # validators write Russian aimed at the person (see
    # `users/schemas._validate_password`). Pydantic prefixes them with
    # "Value error, ". Passing those through is the difference between
    # "Пароль должен содержать хотя бы одну заглавную букву." and a flat
    # "Некорректное значение." that says nothing.
    #
    # Detected by alphabet rather than by a registry: every message pydantic
    # itself produces is English, and every one we write is Russian. Our
    # validators never interpolate the submitted value, which is what makes it
    # safe to forward — the rule the rest of this handler exists to enforce.
    if kind == "value_error":
        own = str(error.get("msg", "")).removeprefix("Value error, ").strip()
        if own and any("а" <= char.lower() <= "я" or char.lower() == "ё" for char in own):
            return own
    # An address is the one field where "Некорректное значение." is uselessly
    # vague, and it is also the commonest thing a person mistypes here.
    location = error.get("loc", ())
    if (
        kind == "value_error"
        and isinstance(location, (list, tuple))
        and any("email" in str(part) for part in location)
    ):
        return "Некорректный адрес электронной почты."
    template = _RU_VALIDATION.get(kind, "Некорректное значение.")
    context = error.get("ctx")
    if isinstance(context, dict):
        try:
            return template.format(**context)
        except (KeyError, IndexError, ValueError):
            # A template whose placeholder this error does not carry: the
            # generic half of the sentence is still true and still Russian.
            return _RU_VALIDATION.get(kind, "Некорректное значение.").split(" — ")[0]
    return template


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Answer a schema violation without echoing what was submitted.

    FastAPI's default handler returns each error with an ``input`` key holding
    the offending value, and a ``ctx`` that can carry more of it. On this API
    that means **a rejected password comes back in the response body**: POST a
    seven-character password to ``/register`` and the 422 contains it in clear,
    where it lands in devtools, in any intermediary's logs, and in whatever
    error reporter the SPA grows next.

    So the value is dropped and only the shape of the complaint survives:
    ``type``, ``loc`` and ``msg`` — which is exactly what the frontend's
    ``extractErrorMessage`` reads, so nothing downstream changes.

    ``loc`` is kept deliberately, even though it names internal field paths: the
    client needs to know WHICH field it got wrong, and the field names are
    already public in the request schema it just submitted.

    ``msg`` is replaced with a Russian rendering — Pydantic writes English, and
    the SPA shows this string to the user unaltered.
    """
    logger.info(
        "Validation error on %s %s (%d field(s)).",
        request.method,
        request.url.path,
        len(exc.errors()),
    )
    return JSONResponse(
        # Starlette renamed the 422 constant; the number is unchanged and this
        # is the spelling it no longer deprecates.
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "detail": [
                {
                    "type": error.get("type", "value_error"),
                    "loc": [str(part) for part in error.get("loc", ())],
                    "msg": _russian_validation_message(error),
                }
                for error in exc.errors()
            ]
        },
    )


@app.get(
    "/health",
    tags=["System"],
    summary="Liveness probe",
    status_code=status.HTTP_200_OK,
    responses={200: {"description": "Service is alive."}},
)
async def health() -> dict[str, str]:
    """Return a static liveness payload for container/orchestrator probes."""
    return {"status": "ok", "service": settings.app_name}


# `/healthz` (readiness: Postgres + Redis) and `/metrics` (Prometheus). Mounted
# here rather than in `main` so this file keeps one subject; see
# `src.core.observability.instrument` for why the exposition is guarded and why
# it is not `Instrumentator.expose()`.
register_observability_routes(app)


# Register module routers under the shared /api prefix.
app.include_router(users_router, prefix="/api")
app.include_router(organizations_router, prefix="/api")
app.include_router(workspaces_router, prefix="/api")
app.include_router(monitoring_router, prefix="/api")
app.include_router(finreports_router, prefix="/api")
app.include_router(ab_tests_router, prefix="/api")
app.include_router(summary_router, prefix="/api")
