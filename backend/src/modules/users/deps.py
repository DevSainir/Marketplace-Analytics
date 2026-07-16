"""Dependency-injection wiring for the Users module.

Assembles the repository -> service graph from the global ``DbSession``. Routers
depend only on :data:`AuthServiceDep`; they never see a session or a repository,
keeping the presentation layer ignorant of persistence.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from src.core.deps import CurrentUserId, DbSession
from src.core.exceptions import AuthenticationError, PermissionDeniedError
from src.modules.users.models import ROLE_DEV, User
from src.modules.users.repos import RefreshTokenRepository, UserRepository
from src.modules.users.services import AuthService


def get_user_repo(session: DbSession) -> UserRepository:
    """Provide a :class:`UserRepository` bound to the request session."""
    return UserRepository(session)


def get_token_repo(session: DbSession) -> RefreshTokenRepository:
    """Provide a :class:`RefreshTokenRepository` bound to the request session."""
    return RefreshTokenRepository(session)


UserRepoDep = Annotated[UserRepository, Depends(get_user_repo)]
TokenRepoDep = Annotated[RefreshTokenRepository, Depends(get_token_repo)]


def get_auth_service(
    user_repo: UserRepoDep,
    token_repo: TokenRepoDep,
) -> AuthService:
    """Compose the :class:`AuthService` from its repository collaborators."""
    return AuthService(user_repo=user_repo, token_repo=token_repo)


#: Clean, injectable service type consumed by the auth routers.
AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


async def get_current_user(user_id: CurrentUserId, user_repo: UserRepoDep) -> User:
    """Resolve the authenticated principal into a live :class:`User` row.

    The JWT layer (:data:`CurrentUserId`) only proves the token; this loads
    the account so role checks always see the *current* database state — a
    role revocation takes effect on the next request, not after token expiry.

    Args:
        user_id: The authenticated user's id from the access token.
        user_repo: User repository bound to the request session.

    Returns:
        The active :class:`User` row.

    Raises:
        AuthenticationError: If the account no longer exists or is disabled.
    """
    user = await user_repo.get_by_id(user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("Account is disabled or no longer exists.")
    return user


#: Injectable authenticated user row (fresh from the database).
CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_dev_role(user: CurrentUser) -> User:
    """Gate a route to users carrying the ``dev`` role.

    Currently the ``dev`` role's single permission: create/delete workspaces
    and manage their WB tokens.

    Args:
        user: The authenticated, freshly loaded user row.

    Returns:
        The same user, for handlers that need the principal.

    Raises:
        PermissionDeniedError: If the user does not hold the ``dev`` role.
    """
    if user.role != ROLE_DEV:
        raise PermissionDeniedError("Developer role required.")
    return user


#: Injectable guard for dev-only routes (workspace administration).
DevUser = Annotated[User, Depends(require_dev_role)]
