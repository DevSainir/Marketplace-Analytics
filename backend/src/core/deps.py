"""Global, cross-cutting FastAPI dependencies.

Only infrastructure-level dependencies live here (database sessions, the
current authenticated principal, integration clients). Module-specific wiring
(repositories, services) lives in each module's own ``deps`` package so that
domains stay decoupled.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, status
from fastapi.exceptions import HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import AsyncSessionLocal
from src.core.logcontext import bind_actor
from src.core.redis import family_revoked_after, sessions_revoked_after
from src.core.security import TokenType, decode_token


async def _commit_and_close(session: AsyncSession) -> None:
    """Commit the request's unit of work, then release the connection."""
    try:
        await session.commit()
    finally:
        await session.close()


async def _rollback_and_close(session: AsyncSession) -> None:
    """Discard the request's unit of work, then release the connection."""
    try:
        await session.rollback()
    finally:
        await session.close()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a request-scoped async SQLAlchemy session (unit of work).

    Implements one transaction per request: the session is committed once the
    route handler returns successfully, and rolled back on any exception, so a
    failed request never leaves a half-applied write behind. Without the commit,
    repository ``flush``es would be discarded when the session closes and no API
    write would ever persist.

    Cleanup is wrapped in :func:`asyncio.shield` and catches ``BaseException``
    deliberately: a client disconnect CANCELS the request task mid-await (the
    ``@app.middleware("http")`` logger runs handlers inside an anyio cancel
    scope), and an unshielded ``rollback``/``close`` would itself be cancelled
    at its first await — leaking the checked-out connection with its
    transaction open. Leaked ``idle in transaction`` connections hold row locks
    (e.g. on ``auth.refresh_tokens``) and exhaust the pool, taking the whole
    API down. The shield lets cleanup finish even while cancellation is being
    delivered; each branch is a single task so rollback/commit and close never
    race on one session.
    """
    session = AsyncSessionLocal()
    try:
        yield session
    except BaseException:  # includes CancelledError/GeneratorExit — see above
        await asyncio.shield(_rollback_and_close(session))
        raise
    else:
        await asyncio.shield(_commit_and_close(session))


#: Reusable type alias injected into every repository dependency.
DbSession = Annotated[AsyncSession, Depends(get_db)]


# ``auto_error=False`` lets us raise a domain-consistent 401 ourselves instead
# of FastAPI's default 403 when the Authorization header is absent.
_bearer_scheme = HTTPBearer(auto_error=False, scheme_name="AccessToken")


async def get_current_user_id(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
) -> uuid.UUID:
    """Resolve and validate the caller's access token into a user id.

    Args:
        credentials: Bearer credentials parsed from the ``Authorization`` header.

    Returns:
        The authenticated user's UUID primary key.

    Raises:
        HTTPException: ``401`` when the token is missing, malformed, expired,
            is not an access token, or was issued before either revocation
            watermark — the per-user one (the incident lever, "log out
            everywhere") or the per-family one (this lineage was logged out, or
            its refresh token was replayed).
    """
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Сессия недействительна или истекла. Войдите снова.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized

    payload = decode_token(credentials.credentials, expected_type=TokenType.ACCESS)
    if payload is None:
        raise unauthorized

    try:
        user_id = uuid.UUID(payload.subject)
    except (ValueError, AttributeError) as exc:
        raise unauthorized from exc

    # Statelessly valid is not enough: a breach response ("revoke all
    # sessions") must also kill outstanding access tokens, not only refresh
    # rows. The Redis watermark makes revocation effective immediately instead
    # of after the 15-minute access TTL.
    revoked_after = await sessions_revoked_after(user_id)
    if revoked_after is not None and payload.issued_at < revoked_after:
        raise unauthorized

    # And the narrow one: this login lineage alone. A logout revokes the
    # family's refresh rows, which used to leave the access token already handed
    # out working for the rest of its TTL.
    #
    # A token carrying no `fam` claim predates it and skips this check rather
    # than being refused. That is what makes the rollout survivable: refusing
    # them would sign every logged-in user out at deploy, to close a window that
    # closes itself within the access TTL anyway.
    if payload.family_id is not None:
        try:
            family_id = uuid.UUID(payload.family_id)
        except ValueError as exc:
            raise unauthorized from exc
        family_revoked = await family_revoked_after(family_id)
        if family_revoked is not None and payload.issued_at < family_revoked:
            raise unauthorized

    # Everything this request logs from here on names the account (P2.2).
    bind_actor(user_id)
    return user_id


#: Injectable authenticated user id for protected routes.
CurrentUserId = Annotated[uuid.UUID, Depends(get_current_user_id)]


async def get_current_family_id(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
) -> uuid.UUID | None:
    """Return the login lineage the caller's access token belongs to.

    Which session am I? Every other check in this module asks "is this token
    still good"; this one asks "which of my sessions is holding it", which is
    what a session list needs to mark one row «этот» ("this one") and what changing a
    password needs to know so it ends the others and not this one.

    Answers ``None`` for a token minted before the ``fam`` claim existed, and
    the caller must treat that as "cannot tell": mark no row current, end no
    session on its say-so. It does NOT re-authorise anything —
    :func:`get_current_user_id` has already refused an invalid token by the time
    a route resolves both.
    """
    if credentials is None:
        return None
    payload = decode_token(credentials.credentials, expected_type=TokenType.ACCESS)
    if payload is None or payload.family_id is None:
        return None
    try:
        return uuid.UUID(payload.family_id)
    except ValueError:
        return None


#: Injectable login-lineage id, or ``None`` for a token that predates the claim.
CurrentFamilyId = Annotated[uuid.UUID | None, Depends(get_current_family_id)]
