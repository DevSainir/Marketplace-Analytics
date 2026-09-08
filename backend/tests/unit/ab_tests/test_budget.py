"""Unit tests for the stop rule (services/budget.py).

This is the trigger a seller was told to trust, so what is pinned here is not
arithmetic but the three-way distinction the whole rule rests on: WB said there
is money, WB said there is none, and WB did not say. The middle one ends an
experiment; the other two must never be mistaken for it.

The failure that would hurt most has no exception in it. If an unreadable budget
resolved to «exhausted», every test would end the first time WB hiccuped, and
the seller would see a finished test with a plausible-looking table.
"""

from __future__ import annotations

import pytest

from src.integrations.wildberries.schemas import WBAdvertV2
from src.modules.ab_tests.services.budget import (
    BudgetState,
    read_state,
    spendable_campaigns,
)

NM_TROUSERS = 1944299862
NM_OTHER = 995716075

#: WB's own status codes, as observed on the live account 2026-09-07.
RUNNING, PAUSED, FINISHED, READY = 9, 11, 7, 4


def _advert(campaign_id: int, *nm_ids: int, status: int = RUNNING) -> WBAdvertV2:
    """One campaign descriptor, shaped as WB's v2 listing sends it."""
    return WBAdvertV2.model_validate(
        {
            "id": campaign_id,
            "status": status,
            "bid_type": "unified",
            "nm_settings": [{"nm_id": nm_id} for nm_id in nm_ids],
        }
    )


class _FakeBudgets:
    """Answers a budget per campaign, or refuses to."""

    def __init__(self, totals: dict[int, int], *, fail_on: int | None = None) -> None:
        self._totals = totals
        self._fail_on = fail_on
        self.asked: list[int] = []

    async def fetch_campaign_budget(self, campaign_id: int) -> int:
        self.asked.append(campaign_id)
        if campaign_id == self._fail_on:
            raise RuntimeError("WB is down")
        return self._totals[campaign_id]


# --------------------------------------------------------------------------- #
# Which campaigns count
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("status", "counts"),
    [
        pytest.param(RUNNING, True, id="идут показы — spending now"),
        pytest.param(PAUSED, True, id="на паузе — money still there, resumable"),
        pytest.param(FINISHED, False, id="завершена — cannot spend whatever it reports"),
        pytest.param(READY, False, id="готова к запуску — never served"),
    ],
)
def test_only_campaigns_that_can_still_spend_are_asked(status: int, counts: bool) -> None:
    """A finished campaign's zero is not evidence about this test's budget.

    261 of the account's campaigns were finished on 2026-09-07 and every one
    reported zero. Counting them would make every test look out of money.
    """
    adverts = [_advert(97455930, NM_TROUSERS, status=status)]

    assert bool(spendable_campaigns(adverts, nm_id=NM_TROUSERS)) is counts


def test_campaigns_for_another_sku_are_not_this_tests_budget() -> None:
    """Money on a different card cannot keep this rotation going."""
    adverts = [_advert(1, NM_OTHER), _advert(2, NM_TROUSERS)]

    assert spendable_campaigns(adverts, nm_id=NM_TROUSERS) == [2]


# --------------------------------------------------------------------------- #
# The three answers
# --------------------------------------------------------------------------- #


async def test_one_funded_campaign_keeps_the_rotation_going() -> None:
    """Any money anywhere is enough — and the rest are not even asked.

    Each id costs a request on a bucket shared with the nightly harvest.
    """
    client = _FakeBudgets({10: 3818, 20: 0, 30: 0})

    assert await read_state(client=client, campaign_ids=[10, 20, 30], nm_id=NM_TROUSERS) is (
        BudgetState.AVAILABLE
    )
    assert client.asked == [10]


async def test_every_campaign_at_zero_is_the_end_of_the_test() -> None:
    """The rule as promised: budget in nought, the test stops."""
    client = _FakeBudgets({10: 0, 20: 0})

    assert await read_state(client=client, campaign_ids=[10, 20], nm_id=NM_TROUSERS) is (
        BudgetState.EXHAUSTED
    )


async def test_a_campaign_wb_will_not_answer_for_poisons_the_whole_answer() -> None:
    """The others being empty does not prove the unreadable one is.

    Returning EXHAUSTED here would end the test on a network blip — silently,
    and with a result table the seller has no reason to distrust.
    """
    client = _FakeBudgets({10: 0, 20: 0}, fail_on=20)

    assert await read_state(client=client, campaign_ids=[10, 20], nm_id=NM_TROUSERS) is (
        BudgetState.UNKNOWN
    )


async def test_a_card_nobody_is_advertising_is_unknown_rather_than_exhausted() -> None:
    """No campaigns is not «the money ran out» — there was never any to run out.

    Vacuous truth would make this EXHAUSTED and stop a test the seller may be
    about to start a campaign for, for a reason the budget rule does not cover.
    """
    client = _FakeBudgets({})

    assert await read_state(client=client, campaign_ids=[], nm_id=NM_TROUSERS) is (
        BudgetState.UNKNOWN
    )
