"""Unit tests for the scheduled pinned-position refresh.

Fakes stand in for the search client and the repository; no network, no Redis,
no Celery. What these pin is the arithmetic that makes three runs a day
affordable at ~1 request per minute — one scan per PHRASE, not per pin — and the
failure policy that keeps one throttled phrase from costing the run the rest.
"""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

import pytest

from src.core.exceptions import IntegrationError
from src.integrations.wildberries.clients.search import SearchPosition, SearchProbe
from src.modules.monitoring.models.pinned_keywords import PinnedKeyword
from src.modules.monitoring.tasks import positions as positions_task
from src.modules.workspaces.contract import WorkspaceTokenBundle

WORKSPACE = uuid.UUID("018f4e2a-0000-7000-8000-000000000001")
FIRST = 953770957
SECOND = 144178006


def _pin(nm_id: int, keyword: str) -> PinnedKeyword:
    return PinnedKeyword(nm_id=nm_id, keyword=keyword)


def _probe(keyword: str, found: dict[int, int]) -> SearchProbe:
    """A probe that located ``found`` (nm_id -> position) for ``keyword``."""
    return SearchProbe(
        query=keyword,
        normalized_query=keyword,
        total_found=7486,
        pages_scanned=3,
        positions_scanned=300,
        truncated=True,
        positions=[
            SearchPosition(nm_id=nm_id, position=pos, page=1, position_on_page=pos)
            for nm_id, pos in found.items()
        ],
    )


class _FakeSearchClient:
    """Records every phrase asked for; optionally throttles some of them."""

    def __init__(self, results: dict[str, Any]) -> None:
        self._results = results
        self.asked: list[str] = []

    async def __aenter__(self) -> _FakeSearchClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def find_positions(self, *, query: str, nm_ids: set[int]) -> SearchProbe:
        self.asked.append(query)
        outcome = self._results[query]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _FakePinRepo:
    """Captures what the run wrote back onto the pins."""

    # Class-level on purpose: the task builds its own repository per phrase (one
    # session per transaction), so the assertions need somewhere shared to look.
    rows: ClassVar[list[PinnedKeyword]] = []
    written: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, _session: object) -> None:
        pass

    async def list_for_workspace(self, **_: Any) -> list[PinnedKeyword]:
        return type(self).rows

    async def record_probe(self, **kwargs: Any) -> None:
        type(self).written.append(kwargs)


class _FakeCardRepo:
    def __init__(self, _session: object) -> None:
        pass

    async def list_workspace_nm_ids(self, _workspace_id: uuid.UUID) -> list[int]:
        return [FIRST, SECOND]


class _FakeSession:
    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def commit(self) -> None:
        return None


async def _fake_bundles(_session: object) -> list[WorkspaceTokenBundle]:
    """The one workspace the aggregation walks; no WB token is needed to probe."""
    return [
        WorkspaceTokenBundle(
            workspace_id=WORKSPACE,
            name="ИП Тест",
            analytics="",
            advertising="",
            content="",
            prices="",
            statistics="",
            marketplace="",
        )
    ]


@pytest.fixture(autouse=True)
def _wire(monkeypatch: pytest.MonkeyPatch) -> None:
    """Swap the module's collaborators for fakes and remove the pacing delay."""
    _FakePinRepo.rows = []
    _FakePinRepo.written = []
    monkeypatch.setattr(positions_task, "AsyncSessionLocal", _FakeSession)
    monkeypatch.setattr(positions_task, "PinnedKeywordRepository", _FakePinRepo)
    monkeypatch.setattr(positions_task, "ProductCardRepository", _FakeCardRepo)
    # The real gap is a minute per phrase; the schedule is what it protects, not
    # anything these tests assert.
    monkeypatch.setattr(positions_task.settings, "wb_search_probe_spacing_seconds", 0)


async def test_one_scan_answers_for_every_sku_pinned_to_that_phrase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two SKUs, one phrase: WB is asked ONCE and both pins get their own rank.

    This is what makes the run affordable three times a day — the probe reads
    whole result pages, so a second SKU on the same phrase is free.
    """
    _FakePinRepo.rows = [_pin(FIRST, "носки мужские"), _pin(SECOND, "носки мужские")]
    client = _FakeSearchClient({"носки мужские": _probe("носки мужские", {FIRST: 7, SECOND: 41})})
    monkeypatch.setattr(positions_task, "build_search_client", lambda _s, **_: client)

    outcome = await positions_task._probe_workspace_pins(WORKSPACE, "ИП Тест")

    assert client.asked == ["носки мужские"]
    assert outcome.counts["pins_updated"] == 2
    assert {w["nm_id"]: w["position"] for w in _FakePinRepo.written} == {FIRST: 7, SECOND: 41}


async def test_a_sku_absent_from_the_scan_is_recorded_as_checked_not_forgotten(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ "Checked, not in the depth" is a result and must overwrite the old rank."""
    _FakePinRepo.rows = [_pin(FIRST, "носки мужские")]
    client = _FakeSearchClient({"носки мужские": _probe("носки мужские", {})})
    monkeypatch.setattr(positions_task, "build_search_client", lambda _s, **_: client)

    await positions_task._probe_workspace_pins(WORKSPACE, "ИП Тест")

    written = _FakePinRepo.written[0]
    assert written["position"] is None
    assert written["positions_scanned"] == 300
    assert written["checked_at"] is not None


async def test_a_throttled_phrase_costs_only_itself(monkeypatch: pytest.MonkeyPatch) -> None:
    """WB refusing one phrase must not abandon the phrases after it.

    The failed pin keeps its previous number AND its previous timestamp, which is
    what tells the seller the card is stale rather than newly unranked.
    """
    _FakePinRepo.rows = [_pin(FIRST, "аaa"), _pin(FIRST, "ббб")]
    client = _FakeSearchClient(
        {
            "аaa": IntegrationError("search.wb.ru не ответил"),
            "ббб": _probe("ббб", {FIRST: 3}),
        }
    )
    monkeypatch.setattr(positions_task, "build_search_client", lambda _s, **_: client)

    outcome = await positions_task._probe_workspace_pins(WORKSPACE, "ИП Тест")

    assert outcome.counts["phrases_failed"] == 1
    assert outcome.counts["phrases"] == 1
    assert [w["keyword"] for w in _FakePinRepo.written] == ["ббб"]
    # Named, not just counted: with several pins the seller otherwise has to
    # compare timestamps by hand to find which number is stale.
    assert outcome.withheld == ("аaa",)


async def test_the_per_run_ceiling_is_reported_not_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A truncated run must say so: stale cards otherwise look current."""
    _FakePinRepo.rows = [_pin(FIRST, f"фраза {i}") for i in range(5)]
    monkeypatch.setattr(positions_task.settings, "wb_search_max_keywords_per_run", 2)
    client = _FakeSearchClient({f"фраза {i}": _probe(f"фраза {i}", {FIRST: 1}) for i in range(5)})
    monkeypatch.setattr(positions_task, "build_search_client", lambda _s, **_: client)

    outcome = await positions_task._probe_workspace_pins(WORKSPACE, "ИП Тест")

    assert outcome.counts["phrases_skipped"] == 3
    assert len(client.asked) == 2


async def test_the_run_payload_carries_the_withheld_phrases_to_the_ui(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The task reports SUCCESS on a refusal, so the payload must say what is missing.

    Prod 2026-08-17: the one pinned phrase was refused twice, the run returned
    SUCCESS having updated nothing, and the panel said «Позиции обновлены.» over
    an unchanged timestamp. ``failed_sources`` is the key the status endpoint
    already forwards for "succeeded and still incomplete".
    """
    _FakePinRepo.rows = [_pin(FIRST, "аaa")]
    client = _FakeSearchClient({"аaa": IntegrationError("search.wb.ru не ответил")})
    monkeypatch.setattr(positions_task, "build_search_client", lambda _s, **_: client)
    monkeypatch.setattr(
        positions_task,
        "load_workspace_token_bundles",
        _fake_bundles,
    )

    payload = await positions_task._refresh_pinned_positions(WORKSPACE)

    assert payload["failed_sources"] == ["аaa"]
    assert payload["pins_updated"] == 0


# --------------------------------------------------------------------------- #
# One phrase, on demand: what «Проверить позицию» enqueues
# --------------------------------------------------------------------------- #
async def test_the_on_demand_check_looks_for_the_whole_catalogue_in_one_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One scan answers for every SKU, so it asks for all of them at once.

    Moved here from the service when the check became a task: WB throttles per IP,
    and a per-SKU scan of the same pages would spend the budget N times over
    information already on the page.
    """
    _FakePinRepo.rows = []
    client = _FakeSearchClient({"носки": _probe("носки", {FIRST: 7})})
    monkeypatch.setattr(positions_task, "build_search_client", lambda _s, **_: client)
    stored: dict[str, object] = {}

    async def fake_store(**kwargs: object) -> None:
        stored.update(kwargs)

    monkeypatch.setattr(positions_task, "store_probe_result", fake_store)

    outcome = await positions_task._probe_one_phrase(WORKSPACE, FIRST, "носки")

    assert client.asked == ["носки"]
    assert outcome["position"] == 7
    # Stored where the read endpoint looks — that is the whole handoff.
    assert stored["query"] == "носки"


async def test_the_on_demand_check_updates_a_pin_on_the_same_phrase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The card and the panel must never disagree about one phrase.

    Checking a phrase that is also pinned writes the fresh sample onto the pin, so
    the card's number and timestamp move with the panel's.
    """
    _FakePinRepo.rows = [_pin(FIRST, "носки")]
    client = _FakeSearchClient({"носки": _probe("носки", {FIRST: 12})})
    monkeypatch.setattr(positions_task, "build_search_client", lambda _s, **_: client)

    async def fake_store(**_: object) -> None:
        return None

    monkeypatch.setattr(positions_task, "store_probe_result", fake_store)

    outcome = await positions_task._probe_one_phrase(WORKSPACE, FIRST, "носки")

    assert outcome["pins_updated"] == 1
    assert [(w["keyword"], w["position"]) for w in _FakePinRepo.written] == [("носки", 12)]
