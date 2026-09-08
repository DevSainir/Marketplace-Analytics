"""When a test has run out of advertising to be measured by.

A rotation used to stop after one lap, which is arbitrary: one lap of a
ten-photo test is ten slots, and whether that is enough traffic to tell the
photos apart has nothing to do with the number ten. So the rotation now cycles,
and the thing that stops it is the thing that was ever really paying for it —
**the advertising budget behind the card**. Budget left: another lap. Budget at
zero: the photo that is up finishes its turn and nothing replaces it.

That rule is only worth having if it can be trusted, so the pieces of it are
spelled out here rather than spread through the poller.

**What counts as "the budget behind the card".** Every campaign that names this
SKU and could still serve it — WB status «идут показы» or «на паузе». A finished
campaign is excluded because it cannot spend whatever it might report, and a
paused one is included because the seller can resume it and its money is still
there.

**Why a zero is believable.** Measured live 2026-09-07 across the account's
campaigns: running ones reported 3818, 3504 and 14929, a paused one 350, and
every finished one 0. The endpoint answers with real numbers, so a zero is an
answer rather than the shape of a failure. See
``WBAdvertisingClient.fetch_campaign_budget``.

**What is NOT a reason to stop.** WB being unreachable, a malformed answer, or a
card with no campaigns at all. None of those mean the money ran out, and a
rotation that stopped on them would end tests for reasons the seller cannot see
or fix. They resolve to :data:`BudgetState.UNKNOWN` and the test keeps going —
the failure that costs a slot is better than the one that ends the experiment.
"""

from __future__ import annotations

import enum
from collections.abc import Iterable, Sequence
from typing import Protocol

from src.core.logging import get_logger
from src.integrations.wildberries.schemas import WBAdvertV2

logger = get_logger(__name__)

#: WB campaign statuses that can still spend money.
#:
#: 9 is «идут показы» and 11 is «на паузе»; 7 is «завершена» and 4 «готова к
#: запуску». Observed on the live account 2026-09-07: 261 campaigns at 7 all
#: reporting a zero budget, 6 at 9 all reporting a positive one, and 47 at 11
#: reporting a mix — which is exactly why a paused campaign counts as money that
#: still exists.
SPENDABLE_STATUSES: frozenset[int] = frozenset({9, 11})


class BudgetState(enum.StrEnum):
    """Whether a test's advertising can still pay for another turn."""

    #: At least one campaign has money left.
    AVAILABLE = "available"
    #: Every campaign that could serve this card reports zero.
    EXHAUSTED = "exhausted"
    #: WB could not be asked. Not a reason to stop.
    UNKNOWN = "unknown"


class _BudgetReader(Protocol):
    """The part of ``WBAdvertisingClient`` the gate needs."""

    async def fetch_campaign_budget(self, campaign_id: int) -> int: ...


def spendable_campaigns(adverts: Iterable[WBAdvertV2], *, nm_id: int) -> list[int]:
    """Campaigns that name this SKU and are not already finished.

    Args:
        adverts: WB's campaign listing.
        nm_id: The card under test.

    Returns:
        Campaign ids, ascending. Empty when nothing can serve this card.
    """
    return sorted(
        advert.campaign_id
        for advert in adverts
        if advert.status in SPENDABLE_STATUSES
        and any(setting.nm_id == nm_id for setting in advert.nm_settings)
    )


async def read_state(
    *, client: _BudgetReader, campaign_ids: Sequence[int], nm_id: int
) -> BudgetState:
    """Ask WB whether any of these campaigns still has budget.

    Stops at the first campaign with money: one is enough to keep the rotation
    going, and each id costs a request on a shallow bucket.

    Args:
        client: Advertising client, already paced by the shared gate.
        campaign_ids: Campaigns that could still serve the card.
        nm_id: The card, for the log line only.

    Returns:
        ``AVAILABLE`` on the first positive budget, ``EXHAUSTED`` when every one
        answered zero, and ``UNKNOWN`` when there was nothing to ask or WB could
        not answer.
    """
    if not campaign_ids:
        # No campaign can serve this card. That is not "the budget ran out" —
        # it is a card nobody is advertising, which the seller may be about to
        # fix. Stopping here would end a test for a reason the budget rule does
        # not cover, so it does not.
        logger.info("ab_tests: nm %s has no spendable campaigns; budget unknown", nm_id)
        return BudgetState.UNKNOWN

    seen_zero = False
    for campaign_id in campaign_ids:
        try:
            total = await client.fetch_campaign_budget(campaign_id)
        except Exception as exc:
            logger.warning(
                "ab_tests: budget unreadable for campaign %s on nm %s: %s", campaign_id, nm_id, exc
            )
            # One unreadable campaign poisons the whole answer on purpose: the
            # others being empty does not prove this one is.
            return BudgetState.UNKNOWN
        if total > 0:
            return BudgetState.AVAILABLE
        seen_zero = True

    return BudgetState.EXHAUSTED if seen_zero else BudgetState.UNKNOWN


__all__ = [
    "SPENDABLE_STATUSES",
    "BudgetState",
    "read_state",
    "spendable_campaigns",
]
