"""Dependency-injection wiring for the Users module.

Assembles the repository -> service graph from the global ``DbSession``. Routers
depend only on :data:`AuthServiceDep`; they never see a session or a repository,
keeping the presentation layer ignorant of persistence.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from src.core.config import settings
from src.core.deps import CurrentUserId, DbSession
from src.core.exceptions import AuthenticationError, PermissionDeniedError
from src.integrations.email import EmailTransport, get_email_transport
from src.modules.users.models import ROLE_DEV, User
from src.modules.users.repos import (
    RefreshTokenRepository,
    UserRepository,
    VerificationCodeRepository,
)
from src.modules.users.services import (
    AccountRecoveryService,
    AuthService,
    RegistrationService,
    VerificationService,
)
from src.modules.users.services.password_change import PasswordChangeService


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


def get_registration_service(user_repo: UserRepoDep) -> RegistrationService:
    """Provide the account-creation service."""
    return RegistrationService(user_repo=user_repo)


RegistrationServiceDep = Annotated[RegistrationService, Depends(get_registration_service)]


def get_email_transport_dep() -> EmailTransport:
    """Provide the process's mail transport.

    A dependency rather than a module-level constant so a component test can
    override it with a fake and read what the flow would have sent — the same
    seam the Redis client has, for the same reason.
    """
    return get_email_transport()


TransportDep = Annotated[EmailTransport, Depends(get_email_transport_dep)]


def get_recovery_service(
    session: DbSession,
    user_repo: UserRepoDep,
    transport: TransportDep,
) -> AccountRecoveryService:
    """Compose the email-confirmation and password-reset service."""
    return AccountRecoveryService(
        users=user_repo,
        verification=VerificationService(codes=VerificationCodeRepository(session)),
        transport=transport,
    )


RecoveryServiceDep = Annotated[AccountRecoveryService, Depends(get_recovery_service)]


def get_password_change_service(
    user_repo: UserRepoDep, token_repo: TokenRepoDep
) -> PasswordChangeService:
    """Compose the signed-in password-change service."""
    return PasswordChangeService(users=user_repo, tokens=token_repo)


PasswordChangeServiceDep = Annotated[PasswordChangeService, Depends(get_password_change_service)]


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
        raise AuthenticationError("Account disabled or no longer exists.")
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
        raise PermissionDeniedError("Only a developer can do this.")
    return user


#: Injectable guard for dev-only routes (workspace administration).
DevUser = Annotated[User, Depends(require_dev_role)]


async def require_confirmed_email(user: CurrentUser) -> User:
    """Gate a route to accounts whose address has been proven.

    **Where this is used, and why not at login.** Refusing an unconfirmed
    account at ``/login`` would make the login response depend on account state,
    and a uniform login answer is a control this codebase has paid for twice
    (P0.1, P1.5). So confirmation is required at the two moments an address
    stops being decorative and starts deciding something: redeeming an
    activation code, which makes the holder an owner, and accepting an
    invitation, which puts them inside somebody's company. Everything before
    that is an account that can reach nothing anyway.

    A no-op while ``EMAIL_CONFIRMATION_REQUIRED`` is off, which is the default
    and is how this ships before a mail relay exists.

    Args:
        user: The authenticated, freshly loaded user row.

    Returns:
        The same user, for handlers that need the principal.

    Raises:
        PermissionDeniedError: When confirmation is required and absent. The
            message says what to do, because unlike a login failure this one is
            told to somebody who has already proven who they are — there is
            nothing left to withhold.
    """
    if not settings.email_confirmation_required:
        return user
    if user.email_confirmed_at is None:
        raise PermissionDeniedError(f"Confirm your email address. We sent a code to {user.email}.")
    return user


#: Injectable guard for routes that need a proven address.
ConfirmedUser = Annotated[User, Depends(require_confirmed_email)]
