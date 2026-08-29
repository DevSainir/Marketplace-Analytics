"""Short-lived memory of the child token a rotation issued.

Three browser tabs share one cookie jar. On page load each fires ``/refresh``
with the **same** refresh secret: the first rotates it, and the other two
present a token that is now consumed. Rotation cannot tell that from a replayed
stolen token, so it revoked the family and signed the user out — a false
positive on every multi-tab user, and a security control that produces those is
one that eventually gets switched off.

The fix is to remember, for a few seconds, which child a consumed token was
rotated into, and serve that same child to a late presenter of the parent
instead of treating them as a thief. Every tab therefore converges on **one**
token: the rotation invariant that makes replay detectable — one live leaf per
family — is preserved, rather than the family being allowed to branch. Outside
the window nothing changes, and a token replayed long after it was consumed
still ends the family, which is the case that actually indicates theft.

It also covers the other benign replay the rotation code documents: a refresh
that succeeded server-side but timed out client-side, which the SPA retries
with a cookie the browser never got to update.

**On storing a live secret.** The child's secret cannot be recovered from the
database, which holds only its SHA-256 digest — so serving it again means
keeping it, and this is the only place in the system that holds a usable refresh
secret at rest. It is Fernet-encrypted with the same key as the WB tokens, it is
namespaced, and it is gone in :data:`~src.core.config.Settings.
refresh_replay_grace_seconds`. That is a deliberate, bounded trade against
signing every multi-tab user out.

Availability: a Redis outage degrades this to the behaviour that shipped before
it — the replay is treated as a breach. It can never degrade to "replays are not
detected".

Setting the window to **0 disables grace entirely**, restoring strict rotation
where every replay ends the family. That is a real operational lever — an
installation that would rather sign multi-tab users out than hold any refresh
secret at rest can choose it — and it is how the breach tests say "outside the
window" without sleeping through one.
"""

from __future__ import annotations

import asyncio
import uuid

from redis.exceptions import RedisError

from src.core.config import settings
from src.core.logging import get_logger
from src.core.redis import get_redis
from src.core.security import SecretDecryptionError, decrypt_secret, encrypt_secret

logger = get_logger(__name__)


#: How long the loser of a simultaneous rotation waits for the winner to record
#: its child, as attempts x delay. A tenth of a second is already generous for
#: "the other request is mid-flight in the same process"; the ceiling exists so
#: a request can never wait on a winner that died.
_RACE_WAIT_ATTEMPTS = 6
_RACE_WAIT_SECONDS = 0.05


def _grace_key(parent_id: uuid.UUID) -> str:
    """Build the key holding the replacement issued for one consumed token."""
    return f"auth:refresh-grace:{parent_id}"


async def remember_rotation(*, parent_id: uuid.UUID, refresh_secret: str) -> None:
    """Record the secret a rotation just issued, so a racing tab can be served it.

    Args:
        parent_id: The token that was consumed to produce this child.
        refresh_secret: The child's opaque secret, stored encrypted.
    """
    if settings.refresh_replay_grace_seconds <= 0:
        return  # Grace disabled: strict rotation, every replay is a breach.
    try:
        await get_redis().set(
            _grace_key(parent_id),
            encrypt_secret(refresh_secret),
            ex=settings.refresh_replay_grace_seconds,
        )
    except (RedisError, SecretDecryptionError):
        # Never let this break the rotation it is describing. Recording the
        # child is an optimisation over signing multi-tab users out; failing to
        # record it costs a false positive, while raising here would cost the
        # refresh itself — the user would be logged out by the very thing meant
        # to stop that. `SecretDecryptionError` is named because
        # `encrypt_secret` raises it when FERNET_SECRET_KEY is absent, and a
        # missing key must degrade this store rather than the login path.
        logger.exception(
            "Could not record the rotation of token %s; a concurrent tab "
            "presenting the same cookie will be treated as a replay.",
            parent_id,
        )


async def recall_rotation(*, parent_id: uuid.UUID) -> str | None:
    """Return the secret already issued for a consumed token, if still in grace.

    Args:
        parent_id: The consumed token being presented again.

    Returns:
        The child's refresh secret, or ``None`` when the window has passed, the
        token was never rotated here, or Redis cannot answer — every one of
        which leaves the caller on its breach path.
    """
    if settings.refresh_replay_grace_seconds <= 0:
        return None
    try:
        stored = await get_redis().get(_grace_key(parent_id))
    except RedisError:
        logger.exception(
            "Redis unavailable: cannot tell a concurrent refresh of token %s from "
            "a replay; treating it as a replay.",
            parent_id,
        )
        return None
    if stored is None:
        return None
    ciphertext = stored.decode("utf-8") if isinstance(stored, bytes) else stored
    try:
        return decrypt_secret(ciphertext)
    except Exception:
        # A key rotation makes old entries undecryptable. That is a lost grace,
        # not a breach signal to suppress — fall through to detection.
        logger.exception("Could not decrypt the grace entry for token %s.", parent_id)
        return None


async def await_rotation(*, parent_id: uuid.UUID) -> str | None:
    """Wait briefly for a rotation that is happening right now to publish itself.

    The sibling of :func:`recall_rotation`, for the other way two tabs collide.
    When they arrive far enough apart, the loser finds the token already
    ``is_used`` and one lookup answers. When they arrive together, both read the
    token as unused and the conditional ``UPDATE`` decides it — and the loser can
    reach this point *before* the winner has finished issuing and recording its
    child. A single lookup would miss by milliseconds and revoke the family,
    which is the same false positive by a narrower margin.

    So the loser of the race waits, briefly and boundedly, for the winner. Only
    that path pays the wait: an ordinary replay of a long-dead token fails its
    ``is_used`` check instead and never gets here.

    Args:
        parent_id: The token both requests presented.

    Returns:
        The winner's child secret, or ``None`` if none appears in time — which
        returns the caller to breach detection.
    """
    if settings.refresh_replay_grace_seconds <= 0:
        return None
    for attempt in range(_RACE_WAIT_ATTEMPTS):
        secret = await recall_rotation(parent_id=parent_id)
        if secret is not None:
            return secret
        if attempt + 1 < _RACE_WAIT_ATTEMPTS:
            await asyncio.sleep(_RACE_WAIT_SECONDS)
    return None


__all__ = ["await_rotation", "recall_rotation", "remember_rotation"]
