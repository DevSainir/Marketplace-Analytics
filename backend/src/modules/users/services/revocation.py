"""Ending sessions: the account-wide lever and the single-lineage one.

Lifted out of :mod:`.auth` because the difference between these two is a
subject of its own, and the rule that separates them is the one most likely to
be got wrong by whoever touches this next.

**Two scopes, two watermarks, and they are not interchangeable.**
:func:`revoke_all_sessions` ends everything an account has open and is the only
operation that may stamp the per-USER watermark. :func:`end_family` ends one
login lineage and stamps the per-FAMILY one. Reaching for the per-user key from
a family-scoped act is what turned one woken-up laptop into a team-wide sign-out
on 2026-07-27; see :func:`src.modules.users.services.breach.revoke_breached_family`.

Free functions taking a repository, matching :mod:`.breach`, rather than methods
on the service — the service delegates and keeps its public surface unchanged.
"""

from __future__ import annotations

import uuid

from src.core.logging import get_logger
from src.core.redis import mark_family_revoked, mark_user_sessions_revoked
from src.core.security import hash_refresh_secret
from src.modules.users.repos import RefreshTokenRepository

logger = get_logger(__name__)


async def revoke_all_sessions(*, tokens: RefreshTokenRepository, user_id: uuid.UUID) -> int:
    """End every session of one account, immediately and on every device.

    The account-wide counterpart of :func:`end_family`, and the one operation
        that legitimately stamps the **per-user** watermark. :func:`end_family` and
        :func:`~src.modules.users.services.breach.revoke_breached_family` both
        refuse to, because that key is per-user and they are per-family — "log out
        of this browser" and "end the lineage that leaked" are not "end
        everything". This is, so it does.

        Both halves are needed and neither is sufficient. Revoking the refresh
        rows stops new pairs being minted but leaves outstanding **access**
        tokens valid for up to their 15-minute TTL, which is exactly the window
        an incident response cannot afford. The watermark closes that window by
        rejecting any access token issued before this moment
        (``get_current_user_id`` checks it on every request). It is also why the
        machinery existed but was unreachable: ``mark_user_sessions_revoked``
        was called from tests only, so the watermark could never be set and
        incident response had no lever at all.

        Order matters. The rows are revoked first and the watermark stamped
        after, so a rotation racing this call finds no live row to rotate. The
        reverse order would leave a gap in which a fresh pair is minted with an
        ``iat`` past the watermark and survives.

        Args:
            tokens: Repository for the account's refresh rows.
            user_id: The account whose sessions all end.

        Returns:
            How many refresh rows were revoked — 0 is a normal answer for an
            account with no live session, not a failure.
    """
    revoked = await tokens.revoke_all_for_user(user_id)
    await mark_user_sessions_revoked(user_id)
    logger.warning("All sessions revoked for user %s (%d refresh rows).", user_id, revoked)
    return revoked


async def end_family(*, tokens: RefreshTokenRepository, refresh_secret: str | None) -> None:
    """Revoke the family associated with a presented refresh token.

    Silent no-op for a missing or unknown token so logout is idempotent and
    cannot be used as a user/token enumeration oracle.

    Family-scoped, and it now stamps a **per-family** watermark. The
    per-USER key is still off limits here for the original reason — it would
    sign every other device of the same account out, and "log out of this
    browser" is not "log out everywhere".

    What changed is the conclusion drawn from that. This used to say a
    per-family watermark "buys nothing against a threat model where the
    attacker already holds the access token", and that reasoning does not
    survive contact with the case logout exists for: someone who believes a
    session is compromised presses it, and the stolen access token from that
    lineage kept working for up to fifteen more minutes. Fifteen minutes of
    an attacker inside the account is exactly what the button was pressed to
    stop. The watermark ends the lineage's access tokens immediately and
    still leaves every other device alone.

    Rows first, watermark second — the reverse leaves a gap in which a
    rotation racing this call mints a pair past the watermark.

    :func:`~src.modules.users.services.breach.revoke_breached_family` uses the
    same scope and now the same watermark; see its docstring for why reuse
    detection stopped revoking account-wide.

    Args:
        tokens: Repository for the presented token's family.
        refresh_secret: The opaque refresh secret from the client cookie, or
            ``None`` when the cookie is absent.
    """
    if not refresh_secret:
        return
    token = await tokens.get_by_hash(hash_refresh_secret(refresh_secret))
    if token is not None:
        await tokens.revoke_family(token.family_id)
        await mark_family_revoked(token.family_id)


__all__ = ["end_family", "revoke_all_sessions"]
