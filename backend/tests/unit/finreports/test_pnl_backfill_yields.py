"""The fresh report outranks the history, and the token only serves one of them.

WB meters `reportDetailByPeriod` at roughly four requests an hour per token, and
two walks want it: the hourly harvest, collecting the report WB published this
morning, and the backfill, filling months that have been missing for months.
Whoever asks first takes the window.

Until now that ordering was luck. On 2026-09-14 the harvest happened to take
09:54 and the backfill's next tick was refused — the right outcome by accident.
Had the backfill asked first, the report a seller opens the app to see would
have waited an hour behind history nobody was waiting for.

The monitoring lanes have yielded to their own harvest since they were written.
These pin the same rule onto the settlement lane.
"""

from __future__ import annotations

import uuid

import pytest

from src.integrations.wildberries.endpoints import (
    SALES_REPORTS_BY_PERIOD_PATH,
    SALES_REPORTS_DETAILED_PATH,
)
from src.integrations.wildberries.rate_limit import FINANCE_REPORT_ENDPOINT_BUCKETS
from src.modules.finreports.constants import HARVEST_LOCK_KEY, HARVEST_LOCK_TTL_SECONDS
from src.modules.finreports.tasks import backfill
from src.modules.finreports.tasks.backfill import walk
from src.modules.workspaces.schemas import WorkspaceTokenBundle


def _tokens() -> WorkspaceTokenBundle:
    """A workspace whose "Finance" and "Statistics" tokens are DIFFERENT.

    Which is the shape one workspace actually has — every other workspace resolves
    both to one `unified` token, and that is why the lane read the wrong bucket
    for a day without anything showing.
    """
    return WorkspaceTokenBundle(
        workspace_id=uuid.UUID("01a07a8d-6e3e-7012-ab9f-34443d93776d"),
        name="Demo",
        statistics="a-statistics-token",
        finance="a-finance-token",
    )


class _FakeRedis:
    def __init__(self, held: bool = False, broken: bool = False) -> None:
        self.held = held
        self.broken = broken

    async def exists(self, key: str) -> int:
        if self.broken:
            raise ConnectionError("redis is down")
        return 1 if (self.held and key == HARVEST_LOCK_KEY) else 0


async def test_the_backfill_stands_aside_while_the_harvest_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole point: the fresh report gets the window."""
    monkeypatch.setattr(backfill, "get_redis", lambda: _FakeRedis(held=True))

    assert await backfill._harvest_is_running() is True


async def test_a_free_lock_does_not_hold_the_backfill_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Yielding to a harvest that is not running would just be a slower lane."""
    monkeypatch.setattr(backfill, "get_redis", lambda: _FakeRedis(held=False))

    assert await backfill._harvest_is_running() is False


async def test_a_redis_outage_lets_the_backfill_continue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail open, like every other Redis-backed control here.

    A backfill running during a cache outage is a smaller problem than one that
    stops for good because it could not ask a question — and the rate gate still
    stands between it and WB either way.
    """
    monkeypatch.setattr(backfill, "get_redis", lambda: _FakeRedis(broken=True))

    assert await backfill._harvest_is_running() is False


def test_the_yield_waits_for_a_token_and_not_for_a_lock_ttl() -> None:
    """What a yielding tick is actually waiting for is the next WB token.

    It used to wait eleven minutes, «just over the harvest's own lock TTL» —
    sized when a settlement request was one of about 94 a day and the harvest
    could hold the endpoint for a quarter of an hour. The Finance surface serves
    one request per minute per method, so a yield of a whole TTL costs the lane
    roughly nine tenths of its throughput whenever a harvest is in flight.

    The TTL is not a runtime anyway: it bounds how long a DEAD holder strands the
    lock, while a live harvest renews it for as long as it runs. Sizing a wait
    against it was sizing against the wrong number in both directions.

    So: at least one refill of the bucket being waited on, and well inside the
    TTL. A tick that wakes into a harvest still walking yields again, which costs
    one Redis read.
    """
    refill = FINANCE_REPORT_ENDPOINT_BUCKETS[SALES_REPORTS_DETAILED_PATH][1]

    assert refill <= backfill._YIELD_SECONDS
    assert backfill._YIELD_SECONDS < HARVEST_LOCK_TTL_SECONDS


class _Gate:
    def __init__(self, shut_for: float) -> None:
        self.shut_for = shut_for
        self.reserve_seen: float | None = None

    async def retry_after(self, _endpoint: str, *, reserve_seconds: float = 0.0) -> float:
        self.reserve_seen = reserve_seconds
        return self.shut_for


async def test_an_open_window_is_not_padded_with_a_second_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A free token means the budget allows a request; waiting is then pure loss.

    This used to be floored at WB's published budget, which sounds safe and is
    not: the bucket is what enforces the budget, and it only reports zero when
    a token is genuinely free and has already outlived the background reserve.
    Adding a window on top of that just idles.

    What survives is a spin guard, for the case where the answer is not
    informative at all — Redis down, `retry_after` failing open to zero.
    """
    monkeypatch.setattr(backfill, "finance_reports_rate_gate", lambda *_a, **_k: _Gate(0.0))

    assert await backfill._next_page_delay(_tokens()) == backfill._MIN_PAGE_GAP_SECONDS


async def test_a_slow_tick_does_not_pay_for_its_own_duration_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bug streaming would otherwise have introduced into its own fix.

    ``retry_after`` is read AFTER the page is ingested, so it already discounts
    the time the tick spent. A 300 s streamed page leaves ~740 s of the window
    to wait; a floor at WB's 930 s budget would make the lane wait 930 s more
    and hand back most of what streaming just saved — and the waste would grow
    with exactly the change meant to speed the walk up.
    """
    monkeypatch.setattr(backfill, "finance_reports_rate_gate", lambda *_a, **_k: _Gate(740.0))

    delay = await backfill._next_page_delay(_tokens())

    assert delay == 740 + backfill._WAKE_MARGIN_SECONDS


async def test_a_block_is_waited_out_using_wb_s_own_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fix for a six-fold self-inflicted slowdown.

    The interval used to be inferred from whether the last page arrived, which
    could not distinguish a penalty from someone else taking the window — so
    contention ratcheted it to 5400 s against an endpoint serving four requests
    an hour. WB states the number in ``x-ratelimit-retry``; the bucket already
    absorbs it, so the lane just reads it.
    """
    monkeypatch.setattr(backfill, "finance_reports_rate_gate", lambda *_a, **_k: _Gate(300.0))

    delay = await backfill._next_page_delay(_tokens())

    assert delay == 300 + backfill._WAKE_MARGIN_SECONDS


async def test_a_long_block_is_polled_rather_than_slept_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ceiling used to be 90 minutes, and the argument for it has reversed.

    Sleeping a long block off in one go was cheaper when waking into it cost a
    request on an endpoint that punished early asks. A tick now reads the
    refusal from Redis before sending anything, so waking is free — and a lane
    asleep for an hour and a half is indistinguishable from a dead one, both to
    the watchdog and to the seller reading the profile.
    """
    # 2762 s is the real penalty one workspace drew on 2026-09-12, read from the bucket's
    # own `blocked_until`.
    monkeypatch.setattr(backfill, "finance_reports_rate_gate", lambda *_a, **_k: _Gate(2762.0))

    assert await backfill._next_page_delay(_tokens()) == backfill._PACE_CEILING_SECONDS


async def test_the_delay_is_read_from_the_finance_token_s_bucket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bucket is keyed per token, so the wrong one is a bucket nobody writes.

    This read `tokens.statistics` while building a FINANCE gate until
    2026-09-23. On a workspace that holds per-surface tokens, that bucket is
    never written and always answers «open», so the lane paced itself on the
    spin guard and could not see a penalty block at all. Every other workspace
    resolves both fields to one `unified` token, which is why it never showed.
    """
    seen: list[str] = []

    def _gate(_settings: object, *, token: str) -> _Gate:
        seen.append(token)
        return _Gate(0.0)

    monkeypatch.setattr(backfill, "finance_reports_rate_gate", _gate)

    await backfill._next_page_delay(_tokens())

    assert seen == ["a-finance-token"]


async def test_the_backfill_asks_as_a_reserving_caller(monkeypatch: pytest.MonkeyPatch) -> None:
    """The history walk must never be first in the queue for a window.

    The reserve is what makes that structural instead of a convention every
    future caller has to remember — and it has to reach the bucket, not just be
    defined. A gate asked without it hands the backfill the freshest slot of
    every window, which is the race this exists to end.
    """
    from src.integrations.wildberries.rate_limit.surfaces import BACKGROUND_RESERVE_SECONDS

    gate = _Gate(0.0)
    monkeypatch.setattr(backfill, "finance_reports_rate_gate", lambda *_a, **_k: gate)

    await backfill._next_page_delay(_tokens())

    assert gate.reserve_seen == BACKGROUND_RESERVE_SECONDS


def test_the_tick_may_live_long_enough_to_finish_a_streamed_page() -> None:
    """The page size and the tick's lifetime are one decision, not two.

    A streamed request carries up to `_STREAM_LIMIT` rows — ~240 MB to download,
    parse, validate and upsert at 100 000. When that outgrows the soft limit the
    failure is not a slow tick but a SILENT one: `SoftTimeLimitExceeded` is not
    the `IntegrationError` the lane catches, so nothing is recorded and nothing
    re-enqueued, which is how this lane was lost for eleven hours on 2026-09-10.

    The budget below is deliberately generous — a minute per 10 000 rows against
    a measured ~60 MB per 25 000 — because the point is not to predict the
    duration but to make raising the page size force a look at this number.
    """
    from src.integrations.wildberries.clients.finance_reports import WBFinanceReportsClient

    seconds_needed = (WBFinanceReportsClient._STREAM_LIMIT / 10_000) * 60

    assert seconds_needed <= backfill._TICK_SOFT_LIMIT_SECONDS, (
        f"a {WBFinanceReportsClient._STREAM_LIMIT}-row page needs ~{seconds_needed:.0f}s of "
        f"headroom; the tick is killed at {backfill._TICK_SOFT_LIMIT_SECONDS}s"
    )


def test_a_hung_tick_is_still_restarted_rather_than_holding_a_slot() -> None:
    """Raising the limit must not outrun the thing that recovers a dead lane."""
    from datetime import timedelta

    from src.modules.workspaces.tasks import STALE_AFTER

    assert timedelta(seconds=backfill._TICK_SOFT_LIMIT_SECONDS) < STALE_AFTER


def test_only_one_tick_may_hold_a_lane(monkeypatch: pytest.MonkeyPatch) -> None:
    """Chains may multiply; a REQUEST may not overlap another.

    The chain token retires a superseded tick only from its second wake onward,
    and a tick enqueued with no chain — what the orphan sweep sends after every
    worker restart — mints a fresh token and proceeds. So each restart bought
    one extra request before anything could retire it. Measured 2026-09-15 after
    a morning of deploys: five ticks in forty minutes, one superseded, requests
    leaving every 8-10 minutes against a budget of one per fifteen, and WB
    answering with a penalty block.

    The loser must also NOT re-enqueue, or the duplicates it was meant to prune
    simply come back on a timer.

    Synchronous on purpose: the Celery task body owns its own event loop, so
    driving it from inside one is not how it runs in production.
    """
    from contextlib import asynccontextmanager
    from typing import Any

    ran: list[str] = []

    @asynccontextmanager
    async def _held(_key: str, **_kw: Any) -> Any:
        yield False  # somebody else holds this lane

    monkeypatch.setattr(backfill, "single_flight", _held)
    monkeypatch.setattr(backfill.celery_app, "send_task", lambda *a, **k: ran.append("enqueued"))

    result = backfill.backfill_pnl.run("01a07a8d-6e3e-7012-ab9f-34443d93776d")

    assert result == {"skipped": "another tick holds this lane"}
    assert ran == [], "a tick that did no work re-enqueued itself anyway"


def test_the_lane_lock_is_per_workspace() -> None:
    """One seller's slow page must not stall another's lane.

    The budget is metered per token, so two workspaces are never in contention;
    a single global lock would invent a queue WB does not impose.
    """
    import uuid as _uuid

    a = backfill._tick_lock_key(_uuid.UUID("01a07a8d-6e3e-7012-ab9f-34443d93776d"))
    b = backfill._tick_lock_key(_uuid.UUID("019f657a-a70c-780a-ac98-f010a1916615"))

    assert a != b


def test_the_lock_outlives_a_missed_renewal_but_not_a_dead_holder() -> None:
    """A TTL sized to the runtime strands the lane when the process dies.

    `single_flight` renews on a heartbeat, so the TTL only has to cover a
    healthy holder failing to renew — not the 217 s a streamed page takes. Sized
    to the runtime instead, a worker killed mid-page (a deploy, the OOM killer)
    would hold the lane for the whole of it.
    """
    assert backfill._TICK_LOCK_TTL_SECONDS < backfill._TICK_SOFT_LIMIT_SECONDS


class _PeriodShut:
    """A gate open on every method but the by-period detail one."""

    async def retry_after(self, endpoint: str, *, reserve_seconds: float = 0.0) -> float:
        return 300.0 if endpoint == SALES_REPORTS_BY_PERIOD_PATH else 0.0


async def test_a_block_on_the_window_method_shuts_the_lane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The window walks its own bucket, so its block has to be read too.

    Only the by-id and list buckets were checked. A 429 on the by-period method
    left the lane reading «open», so each tick asked into the block, failed the
    window, and moved its ceiling past reports it never fetched — until a sweep
    that changed nothing ended the lane with them still owed.
    """
    monkeypatch.setattr(walk, "finance_reports_rate_gate", lambda *_a, **_k: _PeriodShut())
    monkeypatch.setattr(backfill, "finance_reports_rate_gate", lambda *_a, **_k: _PeriodShut())

    shut = await walk._shut_for("a-token")
    delay = await backfill._next_page_delay(_tokens())

    assert shut == 300.0
    assert delay == 300 + backfill._WAKE_MARGIN_SECONDS
