"""Dependency-injection wiring for the Users module.

Assembles the repository -> service graph from the global ``DbSession``. Routers
depend only on :data:`AuthServiceDep`; they never see a session or a repository,
keeping the presentation layer ignorant of persistence.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from src.core.deps import DbSession
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
