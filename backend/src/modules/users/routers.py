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
from src.core.exceptions import ValidationError
from src.core.logging import get_logger
from src.core.ratelimit import RateLimiter

# The audit trail is consumed through the organisations contract, the same
# door every other module uses. The dependency runs one way at import time:
# nothing under users/ is imported by organizations/deps beyond
# users/contract.py, which reaches no further.
from src.modules.organizations.contract import AuditEvent, AuditTrail
from src.modules.users.deps import (
    AuthServiceDep,
    CurrentUser,
    RecoveryServiceDep,
    UserRepoDep,
    require_dev_role,
)
from src.modules.users.schemas import (
    AcceptedResponse,
    EmailConfirmRequest,
    EmailResendRequest,
    IssuedTokens,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    SessionsRevokedResponse,
    TokenPairResponse,
    UserLoginRequest,
    UserRead,
    UserRegisterRequest,
)

router = APIRouter(prefix="/v1/auth", tags=["Authentication"])

logger = get_logger(__name__)

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


# The recovery surface gets its OWN, tighter budget rather than sharing the
# login one. Every endpoint behind it either sends an email or spends a guess
# against a six-digit code, so the thing being rationed is different: mail a
# stranger cannot stop receiving, and attempts against a small keyspace. Five a
# minute per address is far above anyone who has actually lost a password.
_recovery_rate_limit = Depends(
    RateLimiter(
        scope="auth-recovery",
        limit=5,
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
    recovery: RecoveryServiceDep,
    users: UserRepoDep,
) -> UserRead:
    """Register a new user account, and mail it a confirmation code.

    Signup is open and the account starts powerless — it belongs to no
    organisation and every data route sits behind `require_member`. The
    confirmation code is what lets it later take an activation code or an
    invitation (register P1.6).

    The mail is sent inside this request, and a failure to send is NOT allowed
    to fail the registration: the account exists, the password is stored, and
    telling the person "signup failed" would be a lie that also loses their
    password. They can ask for another code from the confirm screen.
    """
    created = await service.register(email=payload.email, password=payload.password)
    account = await users.get_by_email(created.email)
    if account is not None:
        try:
            await recovery.send_confirmation(user=account)
        except Exception:
            logger.exception(
                "Confirmation mail failed for a new account; registration stands and the "
                "code can be re-requested."
            )
    return created


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
    audit: AuditTrail,
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
    await audit.record(
        AuditEvent.SESSIONS_REVOKED,
        target_type="user",
        target_id=user.id,
        metadata={"scope": "self", "revoked": revoked},
    )
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
    audit: AuditTrail,
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
    # The actor is the developer who pulled the lever, the target is the account
    # it was pulled on. Recording only the target would lose the half that
    # matters when the question is later "who ended that person's sessions".
    await audit.record(
        AuditEvent.SESSIONS_REVOKED,
        target_type="user",
        target_id=user_id,
        metadata={"scope": "incident-response", "revoked": revoked},
    )
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


# --------------------------------------------------------------------------- #
# Account recovery (register P1.6)
#
# Four endpoints, one rule running through all of them: **the response never
# says whether an address is registered.** `/login` is carefully not an
# account-existence oracle, and a recovery form that answers "no such user"
# would be the same oracle with a friendlier face — reachable without even a
# password guess. So the two request endpoints always answer 202 with the same
# body, and the two redeem endpoints answer the same way for a wrong code, an
# expired code and an address that never existed.
# --------------------------------------------------------------------------- #
@router.post(
    "/confirm-email",
    response_model=AcceptedResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[_recovery_rate_limit],
    responses={
        200: {"description": "Address confirmed."},
        422: {"description": "The code is wrong, expired, or already used."},
        429: {"description": "Too many attempts; retry later."},
    },
)
async def confirm_email(
    payload: EmailConfirmRequest,
    recovery: RecoveryServiceDep,
) -> AcceptedResponse:
    """Prove control of an address with the code that was mailed to it."""
    if not await recovery.confirm_email(email=payload.email, code=payload.code):
        # One message for every failure. Distinguishing "wrong code" from "no
        # such address" here would hand back exactly what the 202 above spends
        # effort withholding.
        raise ValidationError("Неверный или просроченный код.")
    return AcceptedResponse(detail="Адрес подтверждён.")


@router.post(
    "/resend-confirmation",
    response_model=AcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[_recovery_rate_limit],
    responses={
        202: {"description": "Accepted. Says nothing about whether the address exists."},
        429: {"description": "Too many attempts; retry later."},
    },
)
async def resend_confirmation(
    payload: EmailResendRequest,
    recovery: RecoveryServiceDep,
    users: UserRepoDep,
) -> AcceptedResponse:
    """Send a fresh confirmation code, if there is anybody to send one to.

    Answers 202 whatever it finds — including for an address that was never
    registered, and for one already confirmed.
    """
    account = await users.get_by_email(payload.email.strip().lower())
    if account is not None:
        try:
            await recovery.send_confirmation(user=account)
        except Exception:
            # Swallowed on purpose: a transport failure must not turn into a
            # different response shape, because a different shape is the oracle.
            logger.exception("Confirmation mail failed to send.")
    return AcceptedResponse()


@router.post(
    "/password-reset/request",
    response_model=AcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[_recovery_rate_limit],
    responses={
        202: {"description": "Accepted. Says nothing about whether the address exists."},
        429: {"description": "Too many attempts; retry later."},
    },
)
async def request_password_reset(
    payload: PasswordResetRequest,
    recovery: RecoveryServiceDep,
) -> AcceptedResponse:
    """Mail a reset code, if the address belongs to a live account."""
    if not settings.password_reset_enabled:
        # Answered identically to a successful request. A 404 here would tell an
        # attacker the feature is off, which is a small thing, but the uniform
        # answer costs nothing and this endpoint's whole job is uniformity.
        return AcceptedResponse()
    try:
        await recovery.request_password_reset(email=payload.email)
    except Exception:
        logger.exception("Password-reset mail failed to send.")
    return AcceptedResponse()


@router.post(
    "/password-reset/confirm",
    response_model=AcceptedResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[_recovery_rate_limit],
    responses={
        200: {"description": "Password changed; every session was ended."},
        422: {"description": "The code is wrong, expired, or already used."},
        429: {"description": "Too many attempts; retry later."},
    },
)
async def reset_password(
    payload: PasswordResetConfirmRequest,
    recovery: RecoveryServiceDep,
    service: AuthServiceDep,
    response: Response,
) -> AcceptedResponse:
    """Set a new password against a mailed code, and end every session.

    **Both halves, in this order, in one transaction.** The case this exists for
    is "somebody else may have my password"; changing it while leaving their
    sessions alive would hand the attacker the very thing the reset was meant to
    take away. `revoke_all_sessions` is the operation that legitimately stamps
    the per-user watermark, so the access tokens already issued die immediately
    rather than surviving their remaining TTL (P1.1, P1.12).

    The caller's own refresh cookie is cleared too: they are one of the sessions
    that just ended, and the SPA should send them to the login screen with the
    password they have just chosen.
    """
    if not settings.password_reset_enabled:
        raise ValidationError("Восстановление пароля временно недоступно.")
    user = await recovery.reset_password(
        email=payload.email, code=payload.code, new_password=payload.new_password
    )
    if user is None:
        raise ValidationError("Неверный или просроченный код.")
    await service.revoke_all_sessions(user_id=user.id)
    response.delete_cookie(settings.refresh_cookie_name, path=settings.refresh_cookie_path)
    return AcceptedResponse(detail="Пароль изменён. Войдите заново.")
