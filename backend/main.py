"""FastAPI application entrypoint for the Marketplace Service.

Wires the module routers into a single ASGI app, installs a global exception
handler that maps semantic :class:`AppError` domain errors onto HTTP responses,
and manages the async engine lifecycle. Run with::

    uvicorn main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse

from src.core.config import settings
from src.core.database import dispose_engine
from src.core.exceptions import AppError
from src.core.logging import configure_logging, get_logger
from src.modules.monitoring.routers import router as monitoring_router
from src.modules.users.routers import router as users_router

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup and shutdown.

    Configures logging on startup and disposes of the async engine's connection
    pool on shutdown so the process exits cleanly.
    """
    configure_logging()
    logger.info("Starting %s (env=%s).", settings.app_name, settings.environment)
    yield
    await dispose_engine()
    logger.info("Shutdown complete; database engine disposed.")


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    default_response_class=ORJSONResponse,
    debug=settings.debug,
    lifespan=lifespan,
)

# CORS for the browser frontend. ``allow_credentials`` is required so the
# HttpOnly refresh cookie is accepted; it forbids the ``*`` origin wildcard, so
# explicit origins are configured via settings.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AppError)
async def handle_app_error(request: Request, exc: AppError) -> ORJSONResponse:
    """Translate any uncaught domain :class:`AppError` into an HTTP response.

    This is the single place where escaped business errors become transport
    responses, keeping services free of HTTP concerns.

    Args:
        request: The incoming request (used for logging context).
        exc: The raised domain error carrying a code and suggested status.

    Returns:
        A JSON error envelope with the mapped HTTP status code.
    """
    logger.info("Domain error on %s %s: %s", request.method, request.url.path, exc.code)
    return ORJSONResponse(
        status_code=exc.http_status,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


@app.get("/health", tags=["System"], summary="Liveness probe")
async def health() -> dict[str, str]:
    """Return a static liveness payload for container/orchestrator probes."""
    return {"status": "ok", "service": settings.app_name}


# Register module routers under the shared /api prefix.
app.include_router(users_router, prefix="/api")
app.include_router(monitoring_router, prefix="/api")
