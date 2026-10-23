"""The recorded freshness verdict, and the two ways it must degrade.

This record is the second half of the P&L's freshness line — "and we asked
12 minutes ago". Its whole job is to let a reader tell a quiet week from a dead
harvester, so the failure modes that matter are not "the value is wrong" but
"the value reassures when it should not":

* Redis being unreachable must cost the page one line and nothing else — never
  an exception in the harvest the record annotates, and never a stored value.
* A record that comes back unreadable must degrade to "we have not checked",
  never to a half-parsed verdict. Reassuring from a corrupt record is the worst
  possible failure for a line that exists to reassure.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime

import pytest
from redis.exceptions import RedisError

from src.modules.finreports.services.freshness_record import (
    FreshnessOutcome,
    FreshnessVerdict,
    NullFreshnessRecordStore,
    RedisFreshnessRecordStore,
    freshness_key,
)

pytestmark = pytest.mark.unit

WORKSPACE = uuid.UUID("019f657a-0000-7000-8000-00000000f00d")
CHECKED_AT = datetime(2026, 9, 9, 6, 14, 3, tzinfo=UTC)


class _FakeRedis:
    """An in-memory string store with the two commands the record uses."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.expiries: dict[str, int | None] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, *, ex: int | None = None) -> bool:
        self.store[key] = value
        self.expiries[key] = ex
        return True


class _BrokenRedis:
    """A Redis that is down, in both directions."""

    async def get(self, key: str) -> str | None:
        raise RedisError("connection refused")

    async def set(self, key: str, value: str, *, ex: int | None = None) -> bool:
        raise RedisError("connection refused")


def _store(redis: object, *, ttl_seconds: int = 2_592_000) -> RedisFreshnessRecordStore:
    """A record store over ``redis``, with the production TTL by default."""
    return RedisFreshnessRecordStore(redis, ttl_seconds=ttl_seconds)  # type: ignore[arg-type]


def _verdict(outcome: FreshnessOutcome) -> FreshnessVerdict:
    """A verdict of ``outcome``, probed over one known window."""
    return FreshnessVerdict(
        outcome=outcome,
        checked_at=CHECKED_AT,
        probe_from=date(2026, 9, 7),
        probe_to=date(2026, 9, 8),
    )


# --- the fail-open rule ---------------------------------------------------


def test_only_a_definite_wb_answer_of_nothing_stops_a_harvest() -> None:
    """The gate's asymmetry, stated once, where every call site inherits it.

    A never-harvested workspace and a probe WB never answered both harvest: an
    unanswered question is not a "no", and failing closed there is how one 429
    turns into a settlement week silently missing from the P&L.
    """
    stops = {o for o in FreshnessOutcome if not o.should_harvest}

    assert stops == {
        FreshnessOutcome.UP_TO_DATE,
        FreshnessOutcome.WB_EMPTY,
        # The one deliberate fail-closed. WB has already refused; walking does
        # not fetch the missing report, it lengthens the refusal — measured on
        # 2026-09-17, three requests into a standing block took it from
        # 28 197 s to 302 940 s.
        FreshnessOutcome.RATE_BLOCKED,
    }


# --- round trip -----------------------------------------------------------


async def test_a_recorded_verdict_reads_back_whole() -> None:
    """Outcome, instant and window all survive — the line renders all three."""
    redis = _FakeRedis()
    store = _store(redis)

    await store.put(WORKSPACE, _verdict(FreshnessOutcome.WB_EMPTY))

    assert await store.get(WORKSPACE) == _verdict(FreshnessOutcome.WB_EMPTY)


async def test_a_verdict_is_kept_per_workspace() -> None:
    """One seller's harvest says nothing about another's."""
    redis = _FakeRedis()
    store = _store(redis)
    other = uuid.uuid4()

    await store.put(WORKSPACE, _verdict(FreshnessOutcome.WB_EMPTY))

    assert await store.get(other) is None


async def test_the_entry_outlives_a_harvester_that_stopped_weeks_ago() -> None:
    """The TTL is the signal's lifetime, not a cache's.

    An expired entry is indistinguishable from "never checked", and a stale
    probe is exactly the evidence that the harvester died. A few-hour TTL would
    erase the one thing this line exists to show.
    """
    redis = _FakeRedis()

    await _store(redis).put(WORKSPACE, _verdict(FreshnessOutcome.WB_EMPTY))

    assert redis.expiries[freshness_key(WORKSPACE)] >= 7 * 24 * 60 * 60


# --- degradation ----------------------------------------------------------


async def test_an_unreachable_redis_never_raises_on_the_write() -> None:
    """The harvest must not fall over because its footnote could not be stored."""
    store = _store(_BrokenRedis())

    await store.put(WORKSPACE, _verdict(FreshnessOutcome.WB_HAS_NEW))


async def test_an_unreachable_redis_reads_as_never_checked() -> None:
    """Not as "nothing new" — the page must not invent an answer it does not have."""
    store = _store(_BrokenRedis())

    assert await store.get(WORKSPACE) is None


@pytest.mark.parametrize(
    "raw",
    [
        "not json at all",
        '["wb_empty", "2026-09-09T06:14:03+00:00"]',
        json.dumps({"outcome": "wb_empty"}),
        json.dumps({"outcome": "wb_empty", "checked_at": "not a date"}),
        json.dumps({"outcome": "everything_is_fine", "checked_at": "2026-09-09T06:14:03+00:00"}),
        json.dumps(
            {
                "outcome": "wb_empty",
                "checked_at": "2026-09-09T06:14:03+00:00",
                "probe_to": "2026-13-45",
            }
        ),
    ],
)
async def test_an_unreadable_record_degrades_to_never_checked(raw: str) -> None:
    """Never to a half-parsed verdict — an outcome without its instant reassures.

    "No new reports" is only meaningful next to "asked 12 minutes ago".
    A record that kept the first half and lost the second would say the most
    reassuring thing this feature can say, on no evidence at all — including
    for a value written by a future release whose outcome this code cannot
    read.
    """
    redis = _FakeRedis()
    redis.store[freshness_key(WORKSPACE)] = raw

    assert await _store(redis).get(WORKSPACE) is None


async def test_the_null_store_records_nothing_and_reports_nothing() -> None:
    """The default for tests that are not about the record."""
    store = NullFreshnessRecordStore()

    await store.put(WORKSPACE, _verdict(FreshnessOutcome.WB_EMPTY))

    assert await store.get(WORKSPACE) is None
