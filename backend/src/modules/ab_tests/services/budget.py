"""What the advertising behind a card says the rotation should do next.

A rotation used to stop after one lap, which is arbitrary: one lap of a
ten-photo test is ten slots, and whether that is enough traffic to tell the
photos apart has nothing to do with the number ten. So the rotation cycles, and
the advertising decides — because the advertising is the only thing that was
ever paying for it, and the only thing that makes a photo measurable at all.

Four answers, and the distinctions between them are the whole design:

* **SERVING** — a campaign is running with money in it. Carry on.
* **PAUSED** — the money is there but nothing is running. The seller paused
  their campaigns, so the test pauses too. It is not over: the photo stays on
  the card, nothing advances, no interval is credited to anybody, and the
  rotation picks up by itself when the campaign does. A test that kept rotating
  here would deal photo after photo through dead air and record each one's turn
  as zero impressions — a full table of zeros that reads like a result.
* **EXHAUSTED** — every campaign that could serve this card reports a zero
  budget. That is the end: the photo that is up serves out its turn, and
  nothing replaces it.
* **UNKNOWN** — WB could not be asked, or nobody is advertising this card at
  all. Neither means the money ran out, so neither stops or pauses anything.

**Why a zero is believable.** Measured live 2026-09-07 across the account's
campaigns: running ones reported 3818, 3504 and 14929, a paused one 350, and
every finished one 0. The endpoint answers with real numbers, so a zero is an
answer rather than the shape of a failure. See
``WBAdvertisingClient.fetch_campaign_budget``.
"""

from __future__ import annotations

import enum
from collections.abc import Iterable, Sequence
from typing import Protocol

from src.core.logging import get_logger
from src.integrations.wildberries.schemas import WBAdvertV2

logger = get_logger(__name__)

#: WB status for «идут показы» — the campaign is actually serving right now.
SERVING_STATUS: int = 9

#: WB status for «на паузе» — switched off, but the money is still in it.
PAUSED_STATUS: int = 11

#: Statuses whose campaigns can still spend. A finished campaign (7) cannot, and
#: 261 of the live account's campaigns are finished and all report zero — so
#: counting them would make every test look out of money.
SPENDABLE_STATUSES: frozenset[int] = frozenset({SERVING_STATUS, PAUSED_STATUS})


class AdsState(enum.StrEnum):
    """What the card's advertising says about the rotation."""

    #: A running campaign has money. Keep rotating.
    SERVING = "serving"
    #: Money exists, but every campaign is switched off. Pause with them.
    PAUSED = "paused"
    #: Nothing can spend any more. The test is over.
    EXHAUSTED = "exhausted"
    #: WB could not be asked, or nobody advertises this card. Change nothing.
    UNKNOWN = "unknown"


class _BudgetReader(Protocol):
    """The part of ``WBAdvertisingClient`` the gate needs."""

    async def fetch_campaign_budget(self, campaign_id: int) -> int: ...


def campaigns_by_status(adverts: Iterable[WBAdvertV2], *, nm_id: int, status: int) -> list[int]:
    """Campaign ids naming this SKU that are in one WB status.

    Args:
        adverts: WB's campaign listing.
        nm_id: The card under test.
        status: The WB status to select.

    Returns:
        Campaign ids, ascending.
    """
    return sorted(
        advert.campaign_id
        for advert in adverts
        if advert.status == status and any(setting.nm_id == nm_id for setting in advert.nm_settings)
    )


def spendable_campaigns(adverts: Iterable[WBAdvertV2], *, nm_id: int) -> list[int]:
    """Every campaign naming this SKU that is not already finished.

    Args:
        adverts: WB's campaign listing.
        nm_id: The card under test.

    Returns:
        Campaign ids, ascending. Empty when nothing can serve this card.
    """
    return sorted(
        {
            *campaigns_by_status(adverts, nm_id=nm_id, status=SERVING_STATUS),
            *campaigns_by_status(adverts, nm_id=nm_id, status=PAUSED_STATUS),
        }
    )


async def _any_funded(
    client: _BudgetReader, campaign_ids: Sequence[int], nm_id: int
) -> bool | None:
    """Does any of these campaigns still have budget?

    Stops at the first one that does: one is enough, and each id costs a request
    on a bucket shared with the nightly harvest.

    Args:
        client: Advertising client, already paced by the shared gate.
        campaign_ids: Campaigns to ask about.
        nm_id: The card, for the log line only.

    Returns:
        ``True``/``False``, or ``None`` when WB would not answer for one of
        them — the others being empty does not prove the unreadable one is.
    """
    for campaign_id in campaign_ids:
        try:
            if await client.fetch_campaign_budget(campaign_id) > 0:
                return True
        except Exception as exc:
            logger.warning(
                "ab_tests: budget unreadable for campaign %s on nm %s: %s", campaign_id, nm_id, exc
            )
            return None
    return False


async def read_state(
    *, client: _BudgetReader, adverts: Iterable[WBAdvertV2], nm_id: int
) -> AdsState:
    """Ask WB what the advertising behind one card is doing.

    Running campaigns are asked about first, so the common case — the test is
    fine, carry on — costs one request and stops.

    Args:
        client: Advertising client, already paced by the shared gate.
        adverts: WB's campaign listing for the account.
        nm_id: The card under test.

    Returns:
        See :class:`AdsState`.
    """
    listing = list(adverts)
    serving = campaigns_by_status(listing, nm_id=nm_id, status=SERVING_STATUS)
    paused = campaigns_by_status(listing, nm_id=nm_id, status=PAUSED_STATUS)

    if not serving and not paused:
        # Nobody is advertising this card. That is not «the money ran out» —
        # there was never any to run out — and it is not a pause the seller
        # made either. Stopping or pausing here would act on a rule that does
        # not cover the case.
        logger.info("ab_tests: nm %s has no spendable campaigns; ads state unknown", nm_id)
        return AdsState.UNKNOWN

    serving_funded = await _any_funded(client, serving, nm_id)
    if serving_funded is None:
        return AdsState.UNKNOWN
    if serving_funded:
        return AdsState.SERVING

    paused_funded = await _any_funded(client, paused, nm_id)
    if paused_funded is None:
        return AdsState.UNKNOWN
    if paused_funded:
        logger.info("ab_tests: nm %s has budget but no running campaign; pausing with it", nm_id)
        return AdsState.PAUSED

    return AdsState.EXHAUSTED


__all__ = [
    "PAUSED_STATUS",
    "SERVING_STATUS",
    "SPENDABLE_STATUSES",
    "AdsState",
    "campaigns_by_status",
    "read_state",
    "spendable_campaigns",
]
