"""What a polling pass costs WB (ab_tests/tasks).

The number pinned here is not a performance nicety — it is the difference
between a cabinet that works and one that silently stops.

`/adv/v3/fullstats` is paced by a token bucket of ONE token refilling every
20 seconds, and the bucket is per **seller token**, not per test. So every test
in a cabinet queues behind every other one. When the reads were made per test,
the seventh test in a cabinet pushed the queue past its 120-second cap and the
rest were simply not polled that pass — not an error the seller could see, just
tests that stopped advancing.

The fix is that a fullstats answer already carries a per-SKU breakdown of every
campaign it was asked about, so one call serves the whole cabinet. That makes
the cost of a pass grow with **campaigns in fifties**, and not with tests at
all — which is what these tests state, so that putting the call back inside the
per-test loop breaks something loud.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.integrations.wildberries.schemas import WBAdvCampaignStats
from src.modules.ab_tests.services.collection import counters_by_day
from src.modules.ab_tests.tasks import _CAMPAIGN_BATCH, _read_all_stats

DAYS = [date(2026, 9, 7), date(2026, 9, 8)]

NM_TROUSERS = 1944299862
NM_DRESS = 995716075


class _CountingClient:
    """Records how many times WB was actually asked."""

    def __init__(self, answer: list[WBAdvCampaignStats] | None = None) -> None:
        self.calls: list[list[int]] = []
        self._answer = answer or []

    async def fetch_full_stats(
        self, *, campaign_ids: list[int], date_from: date, date_to: date
    ) -> list[WBAdvCampaignStats]:
        self.calls.append(list(campaign_ids))
        return self._answer


@pytest.mark.parametrize(
    ("campaigns", "expected"),
    [
        pytest.param(1, 1, id="one campaign, one call"),
        pytest.param(50, 1, id="a full batch is still one call"),
        pytest.param(51, 2, id="one over spills into a second"),
        pytest.param(200, 4, id="four batches, whatever the test count"),
    ],
)
async def test_the_cost_of_a_pass_is_counted_in_campaigns_not_tests(
    campaigns: int, expected: int
) -> None:
    """Fifty campaign ids per request, and nothing else moves the number.

    A cabinet with two hundred tests over the same two campaigns costs one
    request; a cabinet with one test over two hundred campaigns costs four.
    """
    client = _CountingClient()

    await _read_all_stats(client, list(range(campaigns)), DAYS)  # type: ignore[arg-type]

    assert len(client.calls) == expected
    assert all(len(batch) <= _CAMPAIGN_BATCH for batch in client.calls)


async def test_a_cabinet_with_nothing_to_ask_about_asks_nothing() -> None:
    """No campaigns is not an empty request, it is no request."""
    client = _CountingClient()

    assert await _read_all_stats(client, [], DAYS) == []  # type: ignore[arg-type]
    assert client.calls == []


def test_one_answer_serves_every_test_in_the_cabinet() -> None:
    """The property the whole batching rests on.

    A fullstats reply breaks each campaign-day down by SKU, so two tests on two
    different articles read two different sets of numbers out of ONE download.
    If this were not true, the per-test call could not have been removed.
    """
    shared = [
        WBAdvCampaignStats.model_validate(
            {
                "advertId": 97455930,
                "days": [
                    {
                        "date": "2026-09-08T00:00:00+03:00",
                        "apps": [
                            {
                                "appType": 1,
                                "nms": [
                                    {"nmId": NM_TROUSERS, "views": 500, "clicks": 20},
                                    {"nmId": NM_DRESS, "views": 300, "clicks": 3},
                                ],
                            }
                        ],
                    }
                ],
            }
        )
    ]

    trousers = counters_by_day(shared, nm_id=NM_TROUSERS)
    dress = counters_by_day(shared, nm_id=NM_DRESS)

    assert [c.views for c in trousers.values()] == [500]
    assert [c.views for c in dress.values()] == [300]
