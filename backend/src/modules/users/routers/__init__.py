"""HTTP routes for authentication.

Grown into a package at the 500-line ceiling: this module owns sessions and
registration, :mod:`.recovery` owns email confirmation and password reset, and
:mod:`.common` holds the rate-limit budgets and the cookie writer they share.
The assembled ``router`` is re-exported here, so callers import exactly what
they did before.

HTTP presentation layer for the Users module.

Routers are pure pass-through: they receive the request, call the service, and
return the result. They set/clear the HttpOnly refresh cookie (a genuine HTTP
presentation concern) but contain **no** business logic and **no**
error-to-HTTP mapping — domain errors (``ConflictError``, ``AuthenticationError``,
``TokenReuseError``) propagate to the global ``AppError`` handler in ``main.py``.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Response, status

from src.core.client_ip import ClientInfo, resolve_client_info
from src.core.config import settings
from src.core.deps import CurrentFamilyId
from src.core.logging import get_logger

# The audit trail is consumed through the organisations contract, the same
# door every other module uses. The dependency runs one way at import time:
# nothing under users/ is imported by organizations/deps beyond
# users/contract.py, which reaches no further.
from src.modules.organizations.contract import AuditEvent, AuditTrail
from src.modules.users.deps import (
    AuthServiceDep,
    CurrentUser,
    PasswordChangeServiceDep,
    RecoveryServiceDep,
    RegistrationServiceDep,
    TokenRepoDep,
    UserRepoDep,
    require_dev_role,
)
from src.modules.users.routers.common import (
    _auth_rate_limit,
    _refresh_rate_limit,
    _set_refresh_cookie,
)
from src.modules.users.routers.recovery import router as recovery_router
from src.modules.users.schemas import (
    PasswordChangedResponse,
    PasswordChangeRequest,
    SessionRead,
    SessionsRevokedResponse,
    TokenPairResponse,
    UserLoginRequest,
    UserRead,
    UserRegisterRequest,
)
from src.modules.users.services.sessions import end_session, list_sessions

router = APIRouter(prefix="/v1/auth", tags=["Authentication"])

logger = get_logger(__name__)

#: Where the caller is, for the row that records the session they are opening.
#: A dependency rather than a `Request` parameter in each handler, so no route
#: can accidentally read `request.client` — the header a client can choose
#: (see :mod:`src.core.client_ip`).
CurrentClient = Annotated[ClientInfo, Depends(resolve_client_info)]


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
    service: RegistrationServiceDep,
    recovery: RecoveryServiceDep,
    users: UserRepoDep,
) -> UserRead:
    """Register a new user account, and mail it a confirmation code.

    Signup is open and the account starts powerless — it belongs to no
    organisation and every data route sits behind `require_member`. The
    confirmation code is what lets it later take an activation code or an
    invitation.

    The mail is sent inside this request, and a failure to send is NOT allowed
    to fail the registration: the account exists, the password is stored, and
    telling the person "signup failed" would be a lie that also loses their
    password. They can ask for another code from the confirm screen.
    """
    outcome = await service.register(email=payload.email, password=payload.password)
    account = await users.get_by_email(outcome.account.email)
    if account is not None:
        try:
            # The password rides on the CODE, not on the account. Whoever
            # redeems it read the mailbox, and applying it there is what stops a
            # stranger's signup for this address from becoming a live account
            # the moment its real owner confirms.
            await recovery.send_confirmation(
                user=account, pending_password_hash=outcome.password_hash
            )
        except Exception:
            logger.exception(
                "Confirmation mail failed for a new account; registration stands and the "
                "code can be re-requested."
            )
    return outcome.account


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
    client: CurrentClient,
) -> TokenPairResponse:
    """Authenticate credentials and issue an access token + refresh cookie."""
    tokens = await service.authenticate(
        email=payload.email, password=payload.password, client=client
    )
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
    client: CurrentClient,
    # The alias keeps the *read* side in lockstep with the configurable name
    # the cookie is *written* under; a hard-coded parameter name would silently
    # break /refresh the day REFRESH_COOKIE_NAME is changed.
    refresh_token: str | None = Cookie(default=None, alias=settings.refresh_cookie_name),
) -> TokenPairResponse:
    """Rotate a refresh token into a brand-new access + refresh pair."""
    tokens = await service.rotate_refresh_token(refresh_secret=refresh_token, client=client)
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
    tokens expired.

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


@router.get(
    "/sessions",
    response_model=list[SessionRead],
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "The caller's own live sessions, newest activity first."},
        401: {"description": "Missing or invalid access token."},
    },
)
async def my_sessions(
    user: CurrentUser,
    tokens: TokenRepoDep,
    current_family: CurrentFamilyId,
) -> list[SessionRead]:
    """List this account's open sessions.

    Guard: ``CurrentUser`` — own-account data, and the narrowest guard that
    works. A membership-derived one would be wrong rather than merely stricter:
    an account with no organisation still has sessions, and being locked out of
    the list of your own logins is not a thing a paywall should decide.

    Scoped by ``user_id`` in the query, never filtered afterwards, so there is
    no arrangement of arguments that returns somebody else's row.

    The response carries no token, no hash and no secret — a session is
    identified by its family id, which is all that ending one needs.
    """
    rows = await list_sessions(tokens=tokens, user_id=user.id)
    return [
        SessionRead(
            family_id=row.family_id,
            user_agent=row.user_agent,
            ip_address=row.ip_address,
            started_at=row.started_at,
            last_seen_at=row.last_seen_at,
            # `None` means the token predates the `fam` claim: mark nothing
            # current rather than guess, or the UI offers to end the session
            # you are sitting in believing it is somebody else's.
            is_current=current_family is not None and row.family_id == current_family,
        )
        for row in rows
    ]


@router.delete(
    "/sessions/{family_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        204: {"description": "That session is over."},
        401: {"description": "Missing or invalid access token."},
        404: {"description": "No such session on this account."},
    },
)
async def end_one_session(
    family_id: uuid.UUID,
    user: CurrentUser,
    tokens: TokenRepoDep,
    audit: AuditTrail,
    response: Response,
    current_family: CurrentFamilyId,
) -> Response:
    """End one named session of the calling account.

    Guard: ``CurrentUser``. Not ``WritingAccess`` — this writes nothing of the
    organisation's and belongs to the same family as ``/logout``: the
    authorisation is the token, and a read-only manager is entitled to end their
    own stolen phone's session.

    Ownership is decided in SQL (``family_belongs_to``), and a lineage belonging
    to somebody else answers **404, not 403**: a family id could only have come
    from another account's list, and confirming it exists would make this an
    oracle. Whoever owns it sees no difference.

    Ending the session you are speaking on is allowed and means logging out —
    the cookie is cleared so the SPA does not keep a dead one around.
    """
    await end_session(tokens=tokens, user_id=user.id, family_id=family_id)
    await audit.record(
        AuditEvent.SESSIONS_REVOKED,
        target_type="user",
        target_id=user.id,
        metadata={"scope": "one-session", "family_id": str(family_id)},
    )
    if current_family is not None and current_family == family_id:
        response.delete_cookie(settings.refresh_cookie_name, path=settings.refresh_cookie_path)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post(
    "/password",
    response_model=PasswordChangedResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[_auth_rate_limit],
    responses={
        200: {"description": "Password changed; the other sessions are over."},
        401: {"description": "Missing token, or the current password is wrong."},
        422: {"description": "The new password is unusable (too weak, public, or unchanged)."},
        429: {"description": "Too many attempts; retry later."},
    },
)
async def change_password(
    payload: PasswordChangeRequest,
    user: CurrentUser,
    service: PasswordChangeServiceDep,
    audit: AuditTrail,
    current_family: CurrentFamilyId,
) -> PasswordChangedResponse:
    """Change your own password, from inside a session.

    Guard: ``CurrentUser`` plus the current password in the body. The second
    half is the one that matters: without it a live session is enough to lock
    the owner out of their own account, and a stolen laptop becomes a stolen
    account. The next-weaker guard — "authenticated" alone — is exactly that
    hole.

    On the auth rate-limit budget, the same one login is on, because guessing
    the current password here is guessing it at ``/login`` by another door.

    Every OTHER session ends. This one does not: whoever changed the password
    has proved themselves twice in the same request, and signing them out would
    be a puzzle rather than a control.
    """
    ended = await service.change(
        user=user,
        current_password=payload.current_password,
        new_password=payload.new_password,
        keep_family_id=current_family,
    )
    await audit.record(
        AuditEvent.SESSIONS_REVOKED,
        target_type="user",
        target_id=user.id,
        metadata={"scope": "password-change", "revoked": ended},
    )
    return PasswordChangedResponse(other_sessions_ended=ended)


# The recovery half lives in its own module (see the package docstring) and is
# folded in here, so `src.modules.users.routers.router` stays the one thing the
# app mounts and nothing outside this package changes.
router.include_router(recovery_router)

__all__ = ["router"]
