"""Email confirmation and password reset — the four routes.

Split from the session routes when the module reached the 500-line ceiling.
They are a coherent half: none of them authenticates with a password, all four
are governed by the non-disclosure rule restated below, and all four are gated
by flags the session routes know nothing about.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from src.core.config import settings
from src.core.deps import DbSession
from src.core.exceptions import ValidationError
from src.core.logging import get_logger
from src.modules.organizations.contract import (
    AuditEvent,
    UnauthenticatedAuditTrail,
    resolve_access,
)
from src.modules.users.deps import AuthServiceDep, RecoveryServiceDep, UserRepoDep
from src.modules.users.routers.common import _recovery_rate_limit, _set_refresh_cookie
from src.modules.users.schemas import (
    AcceptedResponse,
    EmailConfirmRequest,
    EmailResendRequest,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    TokenPairResponse,
)

# No prefix: this router is included INTO the one that carries `/v1/auth`,
# and declaring it here too would serve every route at `/v1/auth/v1/auth/...`.
router = APIRouter(tags=["Authentication"])

logger = get_logger(__name__)


# --------------------------------------------------------------------------- #
# Account recovery
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
    response_model=TokenPairResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[_recovery_rate_limit],
    responses={
        200: {"description": "Address confirmed; the caller is signed in."},
        422: {"description": "The code is wrong, expired, or already used."},
        429: {"description": "Too many attempts; retry later."},
    },
)
async def confirm_email(
    payload: EmailConfirmRequest,
    recovery: RecoveryServiceDep,
    auth: AuthServiceDep,
    response: Response,
) -> TokenPairResponse:
    """Prove control of an address, and sign the caller in.

    **The session is issued here rather than sending them back to /login.**
    Registration deliberately hands out no tokens, so this is the first moment
    an account becomes usable — and by this point the caller has proved both
    halves of the credential: control of the mailbox, and, because the password
    is bound to the code being redeemed, that they are the person who chose it.
    Asking for the password again immediately afterwards would prove nothing
    and lose everyone who set a long one.
    """
    account = await recovery.confirm_email(email=payload.email, code=payload.code)
    if account is None:
        # One message for every failure. Distinguishing "wrong code" from "no
        # such address" here would hand back exactly what the 202 above spends
        # effort withholding.
        raise ValidationError("Неверный или просроченный код.")
    tokens = await auth.issue_session(user_id=account.id)
    _set_refresh_cookie(response, tokens)
    return TokenPairResponse(
        access_token=tokens.access_token,
        expires_at=tokens.access_expires_at,
    )


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
        422: {"description": "Password reset is switched off in this deployment."},
        429: {"description": "Too many attempts; retry later."},
    },
)
async def request_password_reset(
    payload: PasswordResetRequest,
    recovery: RecoveryServiceDep,
) -> AcceptedResponse:
    """Mail a reset code, if the address belongs to a live account."""
    if not settings.password_reset_enabled:
        # This used to answer 202 like everything else, reasoning that a 404
        # would reveal the feature is off and that uniformity "costs nothing".
        # The reasoning was right about the leak and wrong about the cost, and
        # what changed is that the flow now has a UI: a 202 makes the form say a
        # code was sent when the deployment cannot send one, so the user waits
        # for mail that will never arrive instead of contacting support.
        #
        # The uniformity this endpoint exists to protect is PER ADDRESS — that
        # a registered address and an unknown one are indistinguishable. A
        # deployment-wide switch reveals nothing about any account, and is
        # observable anyway by submitting a code and reading `/confirm`'s
        # answer. So the honest failure is the better trade.
        raise ValidationError("Восстановление пароля временно недоступно.")
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
    session: DbSession,
    audit: UnauthenticatedAuditTrail,
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

    **It is recorded.** ``PASSWORD_CHANGED`` was in the audit vocabulary from the
    start with nothing emitting it, because there was no route that changed a
    password. This is that route. A password changing without a
    login is the single most useful line in the trail when the question is "how
    did they get in" — and the address it was done from is the part the account
    holder cannot tell you.

    The actor is passed explicitly because this route is unauthenticated by
    design: identity here is proved by a code delivered to the mailbox, not by a
    token, so the recorder arrives with no actor and receives the one the reset
    established. The organisation is resolved for the same reason — an entry with
    no tenant is invisible to the owner's audit view, which is the person most
    likely to be looking.
    """
    if not settings.password_reset_enabled:
        raise ValidationError("Восстановление пароля временно недоступно.")
    user = await recovery.reset_password(
        email=payload.email, code=payload.code, new_password=payload.new_password
    )
    if user is None:
        raise ValidationError("Неверный или просроченный код.")
    revoked = await service.revoke_all_sessions(user_id=user.id)
    access = await resolve_access(session, user_id=user.id, platform_role=user.role)
    await audit.record(
        AuditEvent.PASSWORD_CHANGED,
        target_type="user",
        target_id=user.id,
        organization_id=access.organization_id,
        actor_user_id=user.id,
        actor_email=user.email,
        metadata={"via": "password-reset", "sessions_revoked": revoked},
    )
    response.delete_cookie(settings.refresh_cookie_name, path=settings.refresh_cookie_path)
    return AcceptedResponse(detail="Пароль изменён. Войдите заново.")
