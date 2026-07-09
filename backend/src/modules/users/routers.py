"""HTTP presentation layer for the Users module.

Routers are pure pass-through: they receive the request, call the service, and
return the result. They set/clear the HttpOnly refresh cookie (a genuine HTTP
presentation concern) but contain **no** business logic and **no**
error-to-HTTP mapping — domain errors (``ConflictError``, ``AuthenticationError``,
``TokenReuseError``) propagate to the global ``AppError`` handler in ``main.py``.
"""

from __future__ import annotations

from fastapi import APIRouter, Cookie, Depends, Response, status

from src.core.config import settings
from src.core.ratelimit import RateLimiter
from src.modules.users.deps import AuthServiceDep
from src.modules.users.schemas import (
    IssuedTokens,
    TokenPairResponse,
    UserLoginRequest,
    UserRead,
    UserRegisterRequest,
)

router = APIRouter(prefix="/v1/auth", tags=["Authentication"])

# One shared per-IP budget across the unauthenticated auth surface: it damps
# credential stuffing on /login, invite guessing on /register, and cookie
# guessing on /refresh (each of which also burns a bcrypt cycle server-side).
_auth_rate_limit = Depends(
    RateLimiter(
        scope="auth",
        limit=settings.auth_rate_limit_attempts,
        window_seconds=settings.auth_rate_limit_window_seconds,
    )
)


def _set_refresh_cookie(response: Response, tokens: IssuedTokens) -> None:
    """Attach the rotated refresh secret as a hardened HttpOnly cookie."""
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=tokens.refresh_secret,
        max_age=settings.refresh_token_ttl_seconds,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite="lax",
        path=settings.refresh_cookie_path,
    )


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_auth_rate_limit],
    responses={
        201: {"description": "User account created."},
        403: {"description": "Registration disabled or invalid invite code."},
        409: {"description": "Email already registered."},
        429: {"description": "Too many attempts; retry later."},
    },
)
async def register(
    payload: UserRegisterRequest,
    service: AuthServiceDep,
) -> UserRead:
    """Register a new user account (requires a valid invite code)."""
    return await service.register(
        email=payload.email,
        password=payload.password,
        invite_code=payload.invite_code,
    )


@router.post(
    "/login",
    response_model=TokenPairResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[_auth_rate_limit],
    responses={
        200: {"description": "Authenticated; access token issued."},
        401: {"description": "Invalid credentials or disabled account."},
        429: {"description": "Too many attempts; retry later."},
    },
)
async def login(
    payload: UserLoginRequest,
    service: AuthServiceDep,
    response: Response,
) -> TokenPairResponse:
    """Authenticate credentials and issue an access token + refresh cookie."""
    tokens = await service.authenticate(email=payload.email, password=payload.password)
    _set_refresh_cookie(response, tokens)
    return TokenPairResponse(
        access_token=tokens.access_token,
        expires_at=tokens.access_expires_at,
    )


@router.post(
    "/refresh",
    response_model=TokenPairResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[_auth_rate_limit],
    responses={
        200: {"description": "Rotated; new token pair issued."},
        401: {"description": "Invalid, expired, revoked, or replayed token."},
        429: {"description": "Too many attempts; retry later."},
    },
)
async def refresh(
    service: AuthServiceDep,
    response: Response,
    # The alias keeps the *read* side in lockstep with the configurable name
    # the cookie is *written* under; a hard-coded parameter name would silently
    # break /refresh the day REFRESH_COOKIE_NAME is changed.
    refresh_token: str | None = Cookie(default=None, alias=settings.refresh_cookie_name),
) -> TokenPairResponse:
    """Rotate a refresh token into a brand-new access + refresh pair."""
    tokens = await service.rotate_refresh_token(refresh_secret=refresh_token)
    _set_refresh_cookie(response, tokens)
    return TokenPairResponse(
        access_token=tokens.access_token,
        expires_at=tokens.access_expires_at,
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={204: {"description": "Session revoked (idempotent)."}},
)
async def logout(
    service: AuthServiceDep,
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=settings.refresh_cookie_name),
) -> Response:
    """Revoke the caller's refresh-token family and clear the cookie."""
    await service.logout(refresh_secret=refresh_token)
    response.delete_cookie(settings.refresh_cookie_name, path=settings.refresh_cookie_path)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
