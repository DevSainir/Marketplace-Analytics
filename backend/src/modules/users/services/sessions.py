"""Seeing your own sessions, and ending the ones you do not recognise.

Until now an account holder had exactly one lever — "Sign out everywhere" — which is
the right thing to reach for when you already know something is wrong and the
wrong thing to need in order to find out. This module is the other half: the
list you look at first, and the aimed version of the same lever.

**A session is a refresh-token FAMILY.** One login opens a lineage that rotates
every fifteen minutes for as long as the browser lives, so a session is one line
here and hundreds of rows in ``auth.refresh_tokens``. Ending one therefore means
revoking the family and stamping the per-family watermark — never the per-user
one, which is «end everything» and belongs to
:func:`~src.modules.users.services.revocation.revoke_all_sessions`. Reaching for
the wrong key here would turn "this phone is not mine" into signing the whole
team out, which is the mistake recorded in that module's docstring.

Free functions taking a repository, matching :mod:`.revocation` and
:mod:`.breach`.
"""

from __future__ import annotations

import uuid

from src.core.exceptions import NotFoundError
from src.core.logging import get_logger
from src.core.redis import mark_family_revoked
from src.modules.users.repos import RefreshTokenRepository, SessionRow

logger = get_logger(__name__)


async def list_sessions(*, tokens: RefreshTokenRepository, user_id: uuid.UUID) -> list[SessionRow]:
    """Every live login lineage of one account, newest activity first.

    Args:
        tokens: Repository bound to the request session.
        user_id: The account asking about itself.

    Returns:
        One row per open session. Empty is a normal answer — an account whose
        only session predates the provenance columns still appears, it simply
        has nothing to say about the device.
    """
    return await tokens.list_sessions(user_id)


async def end_session(
    *, tokens: RefreshTokenRepository, user_id: uuid.UUID, family_id: uuid.UUID
) -> None:
    """End one named login lineage of the calling account.

    Args:
        tokens: Repository bound to the request session.
        user_id: The account acting — every lookup is scoped by it.
        family_id: The lineage to end.

    Raises:
        NotFoundError: When that lineage is not this account's. **404, not
            403**, and deliberately: a family id is a UUID somebody could only
            have got from another account's session list, and confirming that
            it exists would turn this route into an oracle for "is this id a
            real session somewhere". A caller who owns it sees no difference.
    """
    if not await tokens.family_belongs_to(family_id=family_id, user_id=user_id):
        logger.info("Refused to end session %s: not owned by user %s.", family_id, user_id)
        raise NotFoundError("Session not found.")

    # Rows first, watermark second — the reverse leaves a gap in which a
    # rotation racing this call mints a pair past the watermark.
    await tokens.revoke_family(family_id)
    await mark_family_revoked(family_id)
    logger.info("User %s ended session %s.", user_id, family_id)


async def end_other_sessions(
    *, tokens: RefreshTokenRepository, user_id: uuid.UUID, keep_family_id: uuid.UUID | None
) -> int:
    """End every session of this account except the one asking.

    What a password change does. Not
    :func:`~src.modules.users.services.revocation.revoke_all_sessions`, which
    stamps the per-user watermark and would invalidate the caller's own access
    token along with everyone else's — leaving somebody who has just proved
    their identity twice staring at a login screen.

    Args:
        tokens: Repository bound to the request session.
        user_id: The account whose other sessions end.
        keep_family_id: The caller's own lineage, spared. ``None`` for a token
            minted before the ``fam`` claim existed — then nothing is spared,
            because "which one is mine" has no answer and guessing wrong would
            leave the session the attacker is holding alive.

    Returns:
        How many lineages were ended. 0 is normal for an account with one
        session.
    """
    ended = 0
    for family_id in await tokens.live_family_ids(user_id):
        if keep_family_id is not None and family_id == keep_family_id:
            continue
        await tokens.revoke_family(family_id)
        await mark_family_revoked(family_id)
        ended += 1
    if ended:
        logger.warning("Ended %d other session(s) for user %s.", ended, user_id)
    return ended


__all__ = ["end_other_sessions", "end_session", "list_sessions"]
