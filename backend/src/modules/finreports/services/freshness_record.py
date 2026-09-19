"""What the hourly freshness gate found, and somewhere to keep it.

The gate in :mod:`src.modules.finreports.tasks.freshness` asks WB once an hour
whether a settlement report exists that we do not hold. It used to answer
``bool``, log a line and throw the answer away — and that discard is what made a
dead harvester indistinguishable from a quiet week on the P&L page. WB publishes
the weekly report on no fixed day, so "the figures stop at last Sunday" is both
the normal case and the shape of a three-day outage (August 2026, unnoticed).

Two facts make the page honest, and neither works alone. *What we hold* — the
newest report on file — comes from the database. *When we last asked, and what
came back* is this module: a verdict per workspace, recorded by the harvest loop
before it branches, so "asked and there was nothing" leaves the same trace as
"asked and harvested".

**Why Redis and not a table.** This is operational state about the harvester,
not a fact about the seller's money. It has no place in a schema whose
migrations are diffed against the models, it is one small value per workspace,
and losing it costs the page one line.

**Why the TTL is 30 days.** An expired entry is indistinguishable from "never
checked" — and a *stale* probe is precisely the evidence that the harvester
stopped. A few-hour TTL would quietly erase the one signal this feature exists
to show, replacing "nobody has asked since Tuesday" with a blank.
"""

from __future__ import annotations

import enum
import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol

from redis.asyncio import Redis
from redis.exceptions import RedisError

from src.core.logging import get_logger

logger = get_logger(__name__)

#: Redis key namespace for the per-workspace verdict.
_KEY_PREFIX = "finreports:freshness:"


def freshness_key(workspace_id: uuid.UUID) -> str:
    """Build the Redis key holding one workspace's last verdict."""
    return f"{_KEY_PREFIX}{workspace_id}"


class FreshnessOutcome(enum.StrEnum):
    """What the gate found the last time it looked.

    Six outcomes, and the asymmetry between them is the gate's whole rule.

    **Only a definite "WB has nothing" may skip on the strength of the data.**
    A workspace nobody has harvested yet and a probe that never got an answer
    both harvest — an unanswered question is not a "no", and failing closed
    there would postpone a settlement week out of the P&L on one transient WB
    error.

    :attr:`UP_TO_DATE` reaches its skip without asking WB anything, and that is
    not an exception to the rule but the strongest form of it: since 2026-09-19
    it means «we hold a report for every period WB can have formed», derived
    from WB's own period arithmetic (see
    :mod:`src.modules.finreports.services.publication`) rather than from a
    silence we chose to read as a no.

    :attr:`RATE_BLOCKED` is the one place this gate deliberately fails closed,
    and it does so because the alternative is not «ask anyway» but «make the
    block longer»: on 2026-09-17 each request sent into a standing block was
    answered with a longer one, 28 197 s to 302 940 s in three steps.

    :attr:`should_harvest` is where that rule lives, so no call site restates it.
    """

    #: Nothing on file yet — everything WB holds is new, so no probe was made.
    NEVER_HARVESTED = "never_harvested"
    #: The harvested history already reaches yesterday; no unseen day exists to
    #: ask about, so no request was spent.
    UP_TO_DATE = "up_to_date"
    #: WB answered, and answered empty over the days past our history. The one
    #: outcome that proves there is nothing new.
    WB_EMPTY = "wb_empty"
    #: WB served a settled row past our history — a report we do not hold.
    WB_HAS_NEW = "wb_has_new"
    #: WB did not answer (5xx, timeout). Nothing was learned.
    PROBE_FAILED = "probe_failed"
    #: WB has this endpoint shut under a penalty block. Nothing was asked and
    #: nothing may be: a request inside an open block is what makes the next
    #: block longer.
    RATE_BLOCKED = "rate_blocked"

    @property
    def should_harvest(self) -> bool:
        """Whether this outcome lets the harvest run.

        Fails open by construction, with one deliberate exception. The
        outcomes that positively establish "there is nothing to fetch" stop a
        walk; so does :attr:`RATE_BLOCKED`, where WB has already refused and
        walking would only lengthen the refusal.
        """
        return self not in (
            FreshnessOutcome.UP_TO_DATE,
            FreshnessOutcome.WB_EMPTY,
            FreshnessOutcome.RATE_BLOCKED,
        )


@dataclass(frozen=True)
class FreshnessVerdict:
    """One recorded answer from the gate, with the instant it was reached.

    Attributes:
        outcome: What the gate found.
        checked_at: When it found it (UTC).
        probe_from / probe_to: The settlement window actually asked about, or
            ``None`` for the two outcomes that reach a verdict without spending
            a request.
    """

    outcome: FreshnessOutcome
    checked_at: datetime
    probe_from: date | None = None
    probe_to: date | None = None

    @property
    def should_harvest(self) -> bool:
        """Whether the harvest should run — see :attr:`FreshnessOutcome.should_harvest`."""
        return self.outcome.should_harvest

    def to_json(self) -> dict[str, Any]:
        """Serialise to the flat dict stored in Redis."""
        return {
            "outcome": str(self.outcome),
            "checked_at": self.checked_at.isoformat(),
            "probe_from": self.probe_from.isoformat() if self.probe_from else None,
            "probe_to": self.probe_to.isoformat() if self.probe_to else None,
        }

    @classmethod
    def from_json(cls, payload: Any) -> FreshnessVerdict | None:
        """Rebuild a verdict from a stored record, or ``None`` if it is not one.

        Every unreadable shape — a truncated write, a value from a future
        release carrying an outcome this code does not know, anything that is
        not a mapping — degrades to ``None``, which the page renders as "we have
        not checked". **Never to a half-parsed value:** this line exists to
        reassure, and reassuring from a corrupt record is the worst failure it
        could have.
        """
        if not isinstance(payload, dict):
            return None
        try:
            outcome = FreshnessOutcome(payload["outcome"])
            checked_at = datetime.fromisoformat(payload["checked_at"])
            probe_from = payload.get("probe_from")
            probe_to = payload.get("probe_to")
            return cls(
                outcome=outcome,
                checked_at=checked_at,
                probe_from=date.fromisoformat(probe_from) if probe_from else None,
                probe_to=date.fromisoformat(probe_to) if probe_to else None,
            )
        except (KeyError, TypeError, ValueError):
            return None


class FreshnessRecordStore(Protocol):
    """Somewhere to keep the last verdict, one per workspace."""

    async def get(self, workspace_id: uuid.UUID) -> FreshnessVerdict | None:
        """Return the workspace's last verdict, or ``None`` when there is none."""

    async def put(self, workspace_id: uuid.UUID, verdict: FreshnessVerdict) -> None:
        """Record ``verdict`` as the workspace's latest, replacing any previous one."""


class NullFreshnessRecordStore:
    """Records nothing — what tests that are not about the record use."""

    async def get(self, workspace_id: uuid.UUID) -> FreshnessVerdict | None:
        """Always "never checked"."""
        return None

    async def put(self, workspace_id: uuid.UUID, verdict: FreshnessVerdict) -> None:
        """Discard."""


class RedisFreshnessRecordStore:
    """Keeps the last verdict per workspace as JSON in Redis.

    Fails open in both directions, matching :mod:`src.core.redis`'s policy: a
    verdict that cannot be written, or cannot be read back, costs the page one
    line and nothing else. It must never surface as an error to the caller —
    the harvest this annotates is the important half, and a footnote may not
    take it down.
    """

    def __init__(self, redis: Redis, *, ttl_seconds: int) -> None:
        """Wire the store to the shared async Redis client.

        Args:
            redis: The shared ``redis.asyncio.Redis`` (``decode_responses=True``).
            ttl_seconds: Entry expiry. Deliberately long — see the module
                docstring on why a short one erases the signal.
        """
        self._redis = redis
        self._ttl = ttl_seconds

    async def get(self, workspace_id: uuid.UUID) -> FreshnessVerdict | None:
        """Return the stored verdict, or ``None`` when absent, unreachable or corrupt."""
        try:
            raw = await self._redis.get(freshness_key(workspace_id))
        except RedisError:
            logger.warning("Redis unavailable reading the freshness record; reporting unchecked.")
            return None
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
        except ValueError:
            logger.warning("Discarding unparseable freshness record for %s.", workspace_id)
            return None
        verdict = FreshnessVerdict.from_json(payload)
        if verdict is None:
            logger.warning("Discarding unknown-shape freshness record for %s.", workspace_id)
        return verdict

    async def put(self, workspace_id: uuid.UUID, verdict: FreshnessVerdict) -> None:
        """Store the verdict under the workspace's key with the configured TTL."""
        try:
            await self._redis.set(
                freshness_key(workspace_id), json.dumps(verdict.to_json()), ex=self._ttl or None
            )
        except RedisError:
            logger.warning("Redis unavailable writing the freshness record; verdict not stored.")


__all__ = [
    "FreshnessOutcome",
    "FreshnessRecordStore",
    "FreshnessVerdict",
    "NullFreshnessRecordStore",
    "RedisFreshnessRecordStore",
    "freshness_key",
]
