"""Global, cross-cutting FastAPI dependencies.

Only infrastructure-level dependencies live here (database sessions, the
current authenticated principal, integration clients). Module-specific wiring
(repositories, services) lives in each module's own ``deps`` package so that
domains stay decoupled.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, status
from fastapi.exceptions import HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import AsyncSessionLocal
from src.core.redis import sessions_revoked_after
from src.core.security import TokenType, decode_token


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a request-scoped async SQLAlchemy session (unit of work).

    Implements one transaction per request: the session is committed once the
    route handler returns successfully, and rolled back on any exception, so a
    failed request never leaves a half-applied write behind. Without the commit,
    repository ``flush``es would be discarded when the session closes and no API
    write would ever persist.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


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
            is not an access token, or was issued before the user's sessions
            were force-revoked (breach detection / global logout).
    """
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired access token.",
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

    return user_id


#: Injectable authenticated user id for protected routes.
CurrentUserId = Annotated[uuid.UUID, Depends(get_current_user_id)]
