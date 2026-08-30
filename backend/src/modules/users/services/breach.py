"""Ending the login lineage whose refresh token was replayed.

Separated from :mod:`.auth` because it is not a step of authentication: it runs
on its OWN committed transaction, deliberately outside the caller's, and the
long comment inside it is the record of two production incidents. Keeping it
here leaves the service readable and this reasoning findable.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from src.core.database import AsyncSessionLocal
from src.core.logging import get_logger
from src.core.redis import mark_family_revoked
from src.modules.users.repos import RefreshTokenRepository

logger = get_logger(__name__)


async def revoke_breached_family(*, user_id: uuid.UUID, family_id: uuid.UUID) -> None:
    """Kill the login lineage whose refresh token was replayed — and only it.

    Scope is the FAMILY, not the user. This is what RFC 9700 (OAuth 2.0
    Security BCP) §4.14.2 prescribes for detected refresh-token reuse:
    revoke the token chain descended from the replayed token. It is also the
    only scope this code can justify, because a replay is genuinely
    ambiguous — the server cannot tell a thief from a client that legitimately
    holds a superseded token:

    * a laptop resumed from sleep, or a tab restored days later, replays the
      token it went to sleep holding;
    * a rotation that succeeded server-side but timed out client-side is
      retried by the SPA with the same (now consumed) cookie.

    Revoking every family on that evidence is what turned one such replay
    into a team-wide outage on 2026-07-27: a tab last used on the 24th woke
    up, replayed its long-dead token, and signed every other worker sharing
    the account out mid-task, across all 14 of that user's live families.
    Family scope still ends the ambiguous lineage — that device does have to
    log in again — while leaving every other device untouched.

    Revokes in a DEDICATED committed transaction: the calling request ends
    in a 401 (an exception), which rolls back the request-scoped session, so
    the revocation must persist independently or it would be silently undone.

    The per-USER watermark is still never stamped here: that key is
    account-wide, so using it would re-introduce exactly the blast radius this
    scopes away. The **per-family** watermark is stamped, and closes what was
    previously documented as an accepted consequence — access tokens already
    issued on the replayed lineage staying valid for up to fifteen minutes
    (register P1.12). A replay is the strongest evidence available that a
    lineage's tokens are in someone else's hands, so it is the last place worth
    waiting out a TTL.

    Stamped after the rows are revoked, and outside the `try` that guards the
    row update: a lock timeout means the siblings were not marked, but the
    replayed token is already consumed and cannot rotate, so ending the
    lineage's access tokens is still correct and still worth doing.
    """
    logger.warning(
        "Refresh-token reuse detected for user %s; revoking family %s "
        "(other sessions of this user are left intact).",
        user_id,
        family_id,
    )
    async with AsyncSessionLocal() as breach_session:
        # Bound the wait for row locks. This revocation runs on a SECOND
        # connection while the caller's own transaction is still open and
        # may already hold locks on rows in this very family — so the two
        # can wait on each other. Unbounded, that wait ends only when
        # `idle_in_transaction_session_timeout` fires at five minutes, and
        # the request holds a pool slot for all of it.
        #
        # On 2026-07-28 six concurrent refreshes hit this path at once and
        # sat for 300 s each (measured: 300217-300231 ms, all returning
        # 401 in the same second). With the pool that starved, every other
        # user's request queued behind them — the site-wide freeze.
        #
        # Two seconds is far beyond a healthy uncontended UPDATE (~1 ms).
        # Past that, failing the revocation is strictly better than holding
        # the connection: the token was consumed and cannot rotate again, so
        # the replay is already dead — this only defers marking its siblings.
        await breach_session.execute(sa.text("SET LOCAL lock_timeout = '2s'"))
        try:
            await RefreshTokenRepository(breach_session).revoke_family(family_id)
            await breach_session.commit()
        except DBAPIError:
            await breach_session.rollback()
            logger.exception(
                "Could not revoke family %s within the lock timeout; the replayed "
                "token is already consumed, so the session cannot rotate regardless.",
                family_id,
            )
    await mark_family_revoked(family_id)


__all__ = ["revoke_breached_family"]
