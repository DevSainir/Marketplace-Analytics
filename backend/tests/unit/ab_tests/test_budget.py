"""Unit tests for the rule that decides whether a rotation turns (budget.py).

Three answers and **none of them ends a test** — finishing one is the seller's
decision. So what is pinned here is the boundary between «wait» and «carry on»,
and the one case that must never be mistaken for either: WB not answering.

The failure that would hurt most has no exception in it. If an unreadable budget
resolved to «nothing is serving», every test would pause the first time WB
hiccuped, and a seller watching a live campaign would see it stop for no reason
they could find.
"""

from __future__ import annotations

import pytest

from src.integrations.wildberries.schemas import WBAdvertV2
from src.modules.ab_tests.services.budget import (
    PAUSED_STATUS,
    SERVING_STATUS,
    AdsState,
    read_state,
    spendable_campaigns,
)

NM_TROUSERS = 1944299862
NM_OTHER = 995716075

#: WB's own status codes, as the v2 campaign listing reports them.
FINISHED, READY = 7, 4


def _advert(campaign_id: int, *nm_ids: int, status: int = SERVING_STATUS) -> WBAdvertV2:
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
# Which campaigns count at all
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("status", "counts"),
    [
        pytest.param(SERVING_STATUS, True, id="serving — spending now"),
        pytest.param(PAUSED_STATUS, True, id="paused — money still there, resumable"),
        pytest.param(FINISHED, False, id="finished — cannot spend whatever it reports"),
        pytest.param(READY, False, id="ready to start — never served"),
    ],
)
def test_only_campaigns_that_can_still_spend_are_asked(status: int, counts: bool) -> None:
    """A finished campaign's zero is not evidence about this test's budget.

    An account collects hundreds of finished campaigns, and every one of them
    reports zero. Counting them would make every test look out of money.
    """
    adverts = [_advert(97455930, NM_TROUSERS, status=status)]

    assert bool(spendable_campaigns(adverts, nm_id=NM_TROUSERS)) is counts


def test_campaigns_for_another_sku_are_not_this_tests_advertising() -> None:
    """Money on a different card cannot keep this rotation going."""
    adverts = [_advert(1, NM_OTHER), _advert(2, NM_TROUSERS)]

    assert spendable_campaigns(adverts, nm_id=NM_TROUSERS) == [2]


# --------------------------------------------------------------------------- #
# The four answers
# --------------------------------------------------------------------------- #


async def test_a_running_funded_campaign_keeps_the_rotation_going() -> None:
    """The common case costs one request and stops there.

    Running campaigns are asked first for exactly this reason: each id spends
    from a bucket shared with the nightly harvest.
    """
    adverts = [
        _advert(10, NM_TROUSERS),
        _advert(20, NM_TROUSERS),
        _advert(30, NM_TROUSERS, status=PAUSED_STATUS),
    ]
    client = _FakeBudgets({10: 3818, 20: 0, 30: 0})

    assert await read_state(client=client, adverts=adverts, nm_id=NM_TROUSERS) is AdsState.SERVING
    assert client.asked == [10]


async def test_switching_the_campaign_off_pauses_the_test() -> None:
    """The money is still there, so this is a wait and not a result.

    A test that kept rotating here would deal photo after photo through dead
    air and record each turn as zero impressions — ten rows of zeros that read
    exactly like a finding.
    """
    adverts = [_advert(10, NM_TROUSERS, status=PAUSED_STATUS)]
    client = _FakeBudgets({10: 350})

    assert await read_state(client=client, adverts=adverts, nm_id=NM_TROUSERS) is AdsState.PAUSED


async def test_a_running_campaign_with_no_money_is_not_serving() -> None:
    """A "serving" campaign with a zero budget serves nothing, whatever WB calls it."""
    adverts = [_advert(10, NM_TROUSERS)]
    client = _FakeBudgets({10: 0})

    assert await read_state(client=client, adverts=adverts, nm_id=NM_TROUSERS) is AdsState.PAUSED


async def test_a_spent_budget_pauses_rather_than_ends() -> None:
    """A campaign that empties overnight is topped up in the morning.

    Completing here made a routine event permanent: the test could not be
    continued afterwards, and the seller had to build a new one and re-upload
    every photo with none of the measurements carried over. Nothing about a
    zero budget is irreversible, so nothing about it is final.
    """
    adverts = [_advert(10, NM_TROUSERS), _advert(20, NM_TROUSERS, status=PAUSED_STATUS)]
    client = _FakeBudgets({10: 0, 20: 0})

    assert await read_state(client=client, adverts=adverts, nm_id=NM_TROUSERS) is AdsState.PAUSED


async def test_paused_campaigns_are_not_asked_about_their_money() -> None:
    """Once nothing is serving, the answer is the same either way.

    Switched off and switched off with an empty wallet are one state to a test
    that has no traffic to measure, so the extra requests would buy nothing on
    a bucket shared with the nightly harvest.
    """
    adverts = [_advert(10, NM_TROUSERS), _advert(20, NM_TROUSERS, status=PAUSED_STATUS)]
    client = _FakeBudgets({10: 0, 20: 350})

    assert await read_state(client=client, adverts=adverts, nm_id=NM_TROUSERS) is AdsState.PAUSED
    assert client.asked == [10]


async def test_a_campaign_wb_will_not_answer_for_poisons_the_whole_answer() -> None:
    """The others being empty does not prove the unreadable one is.

    Returning PAUSED here would stop a live test on a network blip, and the
    seller would go looking for a campaign problem that does not exist.
    """
    adverts = [_advert(10, NM_TROUSERS), _advert(20, NM_TROUSERS)]
    client = _FakeBudgets({10: 0, 20: 0}, fail_on=20)

    assert await read_state(client=client, adverts=adverts, nm_id=NM_TROUSERS) is AdsState.UNKNOWN


async def test_a_card_nobody_is_advertising_pauses_like_a_switched_off_one() -> None:
    """No campaign at all is nothing to measure, the same as a stopped one.

    It used to read as UNKNOWN, and a "By time" test on such a card dealt
    every photo through dead air — a table of zeros a seller took for a test
    that works without advertising.
    """
    client = _FakeBudgets({})

    assert (
        await read_state(client=client, adverts=[_advert(1, NM_OTHER)], nm_id=NM_TROUSERS)
        is AdsState.PAUSED
    )
    # Nothing to ask a budget of: the listing alone decides it.
    assert client.asked == []


async def test_an_account_with_no_campaigns_at_all_pauses_too() -> None:
    """WB answers ``adverts: null`` for an account that has never advertised.

    That is a real answer, not a failure — a failed listing raises before the
    gate is reached — so it pauses rather than letting the clock deal photos.
    """
    assert await read_state(client=_FakeBudgets({}), adverts=[], nm_id=NM_TROUSERS) is (
        AdsState.PAUSED
    )
