"""A finreports harvest records what it did AND how long it took.

The two halves are one control, not two nice-to-haves. ``HarvestProducingNoRows``
— the alert written after the 2026-07-30 incident, in which every harvest
reported success while its sources silently returned nothing — is:

    sum by (harvest) (increase(harvest_rows_processed_total[6h])) == 0
    and on (harvest) (sum by (harvest) (increase(harvest_duration_seconds_count[6h])) > 0)

The second clause is what separates "ran and wrote nothing" from "did not run",
and it is an ``and on (harvest)`` join. A harvest that reports rows but no
duration has no right-hand series, so the join drops it: the alert cannot fire
for that harvest **at all**, and the Grafana duration panel is blank for it too.

``finreports.finance`` shipped in exactly that state — rows recorded, timer
never called — so this file pins the pairing rather than either counter, which
is the only assertion that would have failed on the code as written.

The counters are process-global and cumulative, so every test here reads a
before and an after and asserts the delta. Nothing is reset: a test that reset
the shared registry would pass alone and corrupt whatever ran beside it.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

import pytest
from prometheus_client import REGISTRY

from src.modules.finreports.tasks import harvest as harvest_module
from src.modules.finreports.tasks.harvest import harvest_workspace
from src.modules.workspaces.contract import WorkspaceTokenBundle

pytestmark = pytest.mark.unit

_WINDOW = (date(2026, 8, 31), date(2026, 9, 6))
_HARVEST = "finreports.finance"


class _FakeSession:
    """The transaction the harvest opens; commits nothing anywhere."""

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def commit(self) -> None:
        return None


class _FakeIngestion:
    """Every ingest reports zero rows — the harvest still ran."""

        return 0

    async def ingest_baselines(self, *_: Any, **__: Any) -> int:
        return 0

        return 0

        return 0


class _ExplodingIngestion(_FakeIngestion):
    """Fails the way a harvest fails: part-way through, after time has passed."""

    async def ingest_baselines(self, *_: Any, **__: Any) -> int:
        raise RuntimeError("WB went away mid-walk")


@pytest.fixture
def harvest_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the harvest's database and its summary warm-up with fakes."""
    monkeypatch.setattr(harvest_module, "AsyncSessionLocal", _FakeSession)
    monkeypatch.setattr(harvest_module, "build_ingestion", lambda _session: _FakeIngestion())

    async def _warm(*, workspace_id: uuid.UUID, name: str) -> None:
        return None

    monkeypatch.setattr(harvest_module, "warm_settlement_rollup", _warm)


def _bundle() -> WorkspaceTokenBundle:
    """A workspace with no WB tokens: nothing to fetch, everything to record.

    The point is the recording, and a tokenless bundle reaches it without any
    WB client being constructed — so this test cannot fail for a reason that
    belongs to the WB integration.
    """
    return WorkspaceTokenBundle(
        workspace_id=uuid.uuid4(),
        name="Демо",
        internal_features=False,
    )


def _duration_count(outcome: str) -> float:
    """Observations of ``harvest_duration_seconds`` for this harvest so far."""
    value = REGISTRY.get_sample_value(
        "harvest_duration_seconds_count", {"harvest": _HARVEST, "outcome": outcome}
    )
    return value or 0.0


def _rows(source: str) -> float | None:
    """Rows recorded against one of this harvest's sources, or ``None``.

    ``None`` and ``0.0`` are different answers and the difference is the whole
    point of the counter: an untouched counter is absent from the exposition,
    and ``rate()`` over an absent series is a gap rather than a zero, which an
    alert reads as "no data". The harvest touches its counters even with zero
    rows so the flat line exists to be alerted on.
    """
    return REGISTRY.get_sample_value(
        "harvest_rows_processed_total", {"harvest": _HARVEST, "source": source}
    )


async def test_a_finance_harvest_records_both_its_rows_and_its_duration(
    harvest_env: None,
) -> None:
    """One harvest produces one duration observation alongside its row counts.

    Asserted as the pair. Either counter alone was already green before the
    timer existed — the rows were being recorded the whole time — and it is
    their coexistence under the same ``harvest`` label that the alert's join
    needs.
    """
    timed_before = _duration_count("ok")

    await harvest_workspace(
        tokens=_bundle(), date_from=_WINDOW[0], date_to=_WINDOW[1], on_date=_WINDOW[1]
    )

    assert _rows("finance") is not None
    assert _duration_count("ok") == timed_before + 1


async def test_a_harvest_that_raises_still_records_the_time_it_burned(
    harvest_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed harvest is timed as ``error``, and the exception still escapes.

    How long a harvest ran before failing is how a fast refusal (a rotated
    token) is told apart from a slow one (WB stalling the socket until the read
    timeout) — so the failure path is the one that must not be skipped. The
    ``pytest.raises`` is half the assertion: a timer that swallowed the error to
    record it would turn every failed harvest into a silent success.
    """
    monkeypatch.setattr(harvest_module, "build_ingestion", lambda _session: _ExplodingIngestion())
    failed_before = _duration_count("error")

    with pytest.raises(RuntimeError, match="went away"):
        await harvest_workspace(
            tokens=_bundle(), date_from=_WINDOW[0], date_to=_WINDOW[1], on_date=_WINDOW[1]
        )

    assert _duration_count("error") == failed_before + 1
