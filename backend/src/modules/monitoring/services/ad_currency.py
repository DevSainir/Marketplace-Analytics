"""Planning the fullstats calls that name the currency of old advertising rows.

Rows harvested before 2026-09-29 were stored without the campaign's currency,
and nothing but WB can say what it was: RUB for campaigns created before WB
moved the ad account to KGS on 2026-08-20, KGS for later ones, both inside one
workspace. fullstats states it on every campaign it answers for, so one call
can label up to fifty campaigns — provided each of them actually delivered
inside the call's window, because fullstats says nothing at all about a
campaign that did not.

Two callers make the calls: :func:`advance_ad_currency`, one call per tick of
the hidden ``ad_currency`` lane (it survives a deploy, like every lane), and
``scripts/backfill/ad_currency.py`` for a run by hand.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.integrations.wildberries import WBAdvertisingClient
from src.modules.monitoring.repos import AdvertisingRepository
from src.modules.workspaces.contract import LaneStep, WorkspaceTokenBundle

#: fullstats caps one request at 31 days.
PROBE_WINDOW_DAYS = 31

#: …and at this many campaign ids (``WBAdvertisingClient._FULLSTATS_BATCH``).
PROBE_BATCH = 50


@dataclass(frozen=True)
class CurrencyProbe:
    """One fullstats call: a window every listed campaign delivered in."""

    begin: date
    end: date
    campaign_ids: list[int]


def plan_currency_probes(
    last_days: dict[int, date],
    *,
    batch: int = PROBE_BATCH,
    window_days: int = PROBE_WINDOW_DAYS,
) -> list[CurrencyProbe]:
    """Group campaigns into as few fullstats calls as their last days allow.

    Each campaign is keyed by its last stored day, which is a day fullstats
    provably answers for it. Walking newest first, a call opens at the newest
    remaining day and takes every campaign whose last day falls within the
    31 days before it, up to the batch size — so an account whose campaigns
    all ran recently costs one call per fifty, and a long tail of old ones
    costs a call per month it spans.

    Args:
        last_days: ``{campaign_id: last stored day}``.
        batch: Most campaign ids per call.
        window_days: Longest window per call.

    Returns:
        The calls, newest window first; each window as narrow as its campaigns.
    """
    ordered = sorted(last_days.items(), key=lambda item: (item[1], item[0]), reverse=True)
    probes: list[CurrencyProbe] = []
    index = 0
    while index < len(ordered):
        end = ordered[index][1]
        floor = end - timedelta(days=window_days - 1)
        ids: list[int] = []
        begin = end
        while index < len(ordered) and len(ids) < batch and ordered[index][1] >= floor:
            campaign_id, day = ordered[index]
            ids.append(campaign_id)
            begin = min(begin, day)
            index += 1
        probes.append(CurrencyProbe(begin=begin, end=end, campaign_ids=sorted(ids)))
    return probes


def _asked(cursor: str | None) -> set[int]:
    """The campaigns earlier ticks already asked WB about."""
    return {int(part) for part in cursor.split(",") if part} if cursor else set()


async def advance_ad_currency(tokens: WorkspaceTokenBundle, *, cursor: str | None) -> LaneStep:
    """Ask WB about ONE batch of unlabelled campaigns and label their rows.

    The cursor is the set of campaigns already asked, not a position: what is
    left to do is read from the data each tick, and the set is what ends the
    walk. A campaign fullstats answers without a currency, or not at all, stays
    unlabelled — and without the set it would be planned again every tick,
    forever.

    Args:
        tokens: The workspace's decrypted credentials.
        cursor: Comma-separated campaign ids already asked; ``None`` at start.

    Returns:
        The step — one WB request's worth of work.
    """
    if not tokens.advertising:
        return LaneStep(0, 0, None, True, "Нет токена «Продвижение» — валюта рекламы не размечена.")

    asked = _asked(cursor)
    async with AsyncSessionLocal() as session:
        missing = await AdvertisingRepository(session).campaigns_without_currency(
            workspace_id=tokens.workspace_id
        )
    probes = plan_currency_probes({cid: day for cid, day in missing.items() if cid not in asked})
    if not probes:
        return LaneStep(len(asked), len(asked), None, True, "Валюта рекламы размечена.")

    probe = probes[0]
    async with WBAdvertisingClient(settings, token=tokens.advertising) as client:
        stats = await client.fetch_full_stats(
            campaign_ids=probe.campaign_ids, date_from=probe.begin, date_to=probe.end
        )
    labelled = 0
    async with AsyncSessionLocal() as session:
        repo = AdvertisingRepository(session)
        for campaign in stats:
            if campaign.currency:
                labelled += await repo.label_campaign_currency(
                    workspace_id=tokens.workspace_id,
                    campaign_id=campaign.campaign_id,
                    currency=campaign.currency,
                )
        # A row now labelled RUB is rouble money like any other: convert it.
        await repo.convert_rouble_money(campaign_ids=[c.campaign_id for c in stats])
        await session.commit()

    asked |= set(probe.campaign_ids)
    finished = len(probes) == 1
    remaining = sum(len(later.campaign_ids) for later in probes[1:])
    return LaneStep(
        done=len(asked),
        total=len(asked) + remaining,
        cursor=None if finished else ",".join(str(cid) for cid in sorted(asked)),
        finished=finished,
        message=f"Размечаем валюту рекламы: {len(asked)} из {len(asked) + remaining} кампаний.",
        rows=labelled,
    )
