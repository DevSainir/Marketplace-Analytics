"""HTTP presentation layer for the Users module.

Routers are pure pass-through: they receive the request, call the service, and
return the result. They set/clear the HttpOnly refresh cookie (a genuine HTTP
presentation concern) but contain **no** business logic and **no**
error-to-HTTP mapping — domain errors (``ConflictError``, ``AuthenticationError``,
``TokenReuseError``) propagate to the global ``AppError`` handler in ``main.py``.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Cookie, Depends, Response, status

from src.core.config import settings
from src.core.ratelimit import RateLimiter
from src.modules.users.deps import AuthServiceDep, CurrentUser, require_dev_role
from src.modules.users.schemas import (
    IssuedTokens,
    SessionsRevokedResponse,
    TokenPairResponse,
    UserLoginRequest,
    UserRead,
    UserRegisterRequest,
)

router = APIRouter(prefix="/v1/auth", tags=["Authentication"])

# One shared per-IP budget across /login + /register: it damps credential
# stuffing and invite guessing (each of which also burns a bcrypt cycle
# server-side).
_auth_rate_limit = Depends(
    RateLimiter(
        scope="auth",
        limit=settings.auth_rate_limit_attempts,
        window_seconds=settings.auth_rate_limit_window_seconds,
    )
)

# /refresh has its own, looser budget: its secret is an unguessable random
# cookie (not a password), and the SPA calls it silently on every page load
# and ~every 14 minutes per tab — sharing the login budget starved legitimate
# sessions into 429s, which the frontend read as "logged out".
_refresh_rate_limit = Depends(
    RateLimiter(
        scope="auth-refresh",
        limit=settings.refresh_rate_limit_attempts,
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
        409: {"description": "Email already registered."},
        429: {"description": "Too many attempts; retry later."},
    },
)
async def register(
    payload: UserRegisterRequest,
    service: AuthServiceDep,
) -> UserRead:
    """Register a new user account. Signup is open; the account starts powerless."""
    return await service.register(
        email=payload.email,
        password=payload.password,
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
    dependencies=[_refresh_rate_limit],
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


@router.get(
    "/me",
    response_model=UserRead,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "The authenticated user's account."},
        401: {"description": "Missing or invalid access token."},
    },
)
async def me(user: CurrentUser) -> UserRead:
    """Return the authenticated caller's account (email + role for the UI)."""
    return UserRead.model_validate(user)


@router.post(
    "/logout-all",
    response_model=SessionsRevokedResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Every session of the calling account was ended."},
        401: {"description": "Missing or invalid access token."},
    },
)
async def logout_everywhere(
    user: CurrentUser,
    service: AuthServiceDep,
    response: Response,
) -> SessionsRevokedResponse:
    """End every session of the calling account, on every device, now.

    ``/logout`` ends the browser you are in. This ends all of them — the phone
    left at a customer's office, the session opened on a shared machine, the one
    whose password you have just changed because you are not sure.

    Unlike ``/logout`` it also stamps the Redis revocation watermark, so the
    access tokens already handed out stop working immediately rather than
    surviving up to their 15-minute lifetime. That is the difference between
    "signed out" and "cannot act", and it is the only place we make it.

    The caller's own session ends too: this is deliberate, since a user who
    presses it has usually decided the account is not to be trusted right now.
    The cookie is cleared so the SPA returns to the login screen.
    """
    revoked = await service.revoke_all_sessions(user_id=user.id)
    response.delete_cookie(settings.refresh_cookie_name, path=settings.refresh_cookie_path)
    return SessionsRevokedResponse(revoked=revoked)


@router.post(
    "/sessions/{user_id}/revoke",
    response_model=SessionsRevokedResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_dev_role)],
    responses={
        200: {"description": "Every session of the named account was ended."},
        401: {"description": "Missing or invalid access token."},
        403: {"description": "Developer role required."},
    },
)
async def revoke_account_sessions(
    user_id: uuid.UUID,
    service: AuthServiceDep,
) -> SessionsRevokedResponse:
    """End every session of another account — the incident-response lever.

    A compromised account has to be stoppable by someone other than whoever
    controls it, and until now nobody could: the revocation watermark had no
    caller outside the test suite, so a stolen session simply ran until its
    tokens expired (register P1.1).

    Answers 200 for an account that does not exist, with ``revoked: 0``,
    exactly as for one that exists and holds no session. The endpoint is behind
    the developer role, so this is not much of a secret — but an id oracle costs
    nothing to avoid and the caller has no use for the distinction.
    """
    revoked = await service.revoke_all_sessions(user_id=user_id)
    return SessionsRevokedResponse(revoked=revoked)


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
