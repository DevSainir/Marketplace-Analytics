"""The demo's A/B photo tests: one finished, one paused, one still a draft.

A test is read entirely from its own tables — the rotation, its rounds and the
per-window counters the poller would have collected — so a finished test needs
no WB to be shown. None of them is left ``running``: the rotation poller would
pick a running test up every five minutes, and with no token it could only log
that it cannot.

The photos are generated placeholders (:mod:`scripts.seed_demo.photos`) saved
through the module's own media store, exactly where an upload would land.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from scripts.seed_demo import simulation as sim
from scripts.seed_demo.catalogue import CAMPAIGNS, CURRENCY, SKU_BY_NM, DemoCampaign
from scripts.seed_demo.photos import placeholder_photo
from src.core.config import settings
from src.core.timeutils import MOSCOW_TZ
from src.modules.ab_tests.models import (
    AbTest,
    AbTestCampaign,
    AbTestStatus,
    AbTestVariant,
    TriggerMode,
    VariantExposure,
    VariantStatWindow,
)
from src.modules.ab_tests.services.storage import build_media_store

#: (letter, backdrop, garment, click-through relative to the original).
_LOOKS: tuple[tuple[str, str, str, float], ...] = (
    ("A", "#EDEAE4", "#6B7350", 1.0),
    ("B", "#DCE6EE", "#4F5D3C", 1.24),
    ("C", "#F3E3D3", "#8A8F6A", 0.83),
)

#: The A/B module's names for the campaign kinds (``services/campaigns.py``).
_KIND = {("unified", "cpm"): "uni", ("manual", "cpm"): "manual_search", ("manual", "cpc"): "cpc"}


@dataclass(frozen=True)
class _Plan:
    """How one test ran: its article, campaigns, rhythm and how far it got."""

    name: str
    nm_id: int
    status: AbTestStatus
    trigger: TriggerMode
    variants: int
    created: datetime
    started: datetime | None
    slot_minutes: int
    exposures: int
    window_minutes: int


def _campaigns_for(nm_id: int) -> list[DemoCampaign]:
    """The campaigns advertising an article — what a test on it is measured by."""
    return [campaign for campaign in CAMPAIGNS if campaign.nm_id == nm_id]


def _kind(campaign: DemoCampaign) -> str:
    """The register's kind for a campaign; shelves-only manual is its own kind."""
    if campaign.bid_type == "manual" and not campaign.search:
        return "manual_shelves"
    return _KIND[(campaign.bid_type, campaign.payment_type)]


def _plans(today: date) -> list[_Plan]:
    """The three tests, anchored to days before ``today``."""

    def at(days_ago: int, hour: int) -> datetime:
        return datetime.combine(today - timedelta(days=days_ago), time(hour), tzinfo=MOSCOW_TZ)

    skus = sorted(SKU_BY_NM)
    return [
        _Plan(
            "Hoodie main photo: three angles", skus[3], AbTestStatus.CANCELLED,
            TriggerMode.TIME, 3, at(10, 17), at(9, 10), 60, 12, 15,
        ),
        _Plan(
            "Trousers: studio or street", skus[0], AbTestStatus.PAUSED,
            TriggerMode.TIME, 3, at(4, 18), at(3, 11), 90, 4, 30,
        ),
        _Plan(
            "T-shirt: white background or styled look", skus[5], AbTestStatus.DRAFT,
            TriggerMode.IMPRESSIONS, 2, at(1, 15), None, 60, 0, 30,
        ),
    ]  # fmt: skip


def _windows(
    test: AbTest, variant: AbTestVariant, look: float, start: datetime, plan: _Plan
) -> list[VariantStatWindow]:
    """The poller's counters for one exposure, per campaign and window."""
    rows: list[VariantStatWindow] = []
    for campaign in _campaigns_for(plan.nm_id):
        per_minute = campaign.views * 1.4 / (24 * 60)
        for offset in range(0, plan.slot_minutes, plan.window_minutes):
            window_start = start + timedelta(minutes=offset)
            jitter = sim.noise(0.18, "ab", campaign.campaign_id, window_start)
            views = round(per_minute * plan.window_minutes * jitter)
            clicks = round(views * campaign.ctr * look * sim.noise(0.2, "abc", window_start))
            if campaign.payment_type == "cpc":
                spend = sim.money(Decimal(clicks) * campaign.rate)
            else:
                spend = sim.money(Decimal(views) * campaign.rate / 1000)
            rows.append(
                VariantStatWindow(
                    test_id=test.id,
                    variant_id=variant.id,
                    campaign_id=campaign.campaign_id,
                    window_start=window_start,
                    window_end=window_start + timedelta(minutes=plan.window_minutes),
                    views=views,
                    clicks=clicks,
                    atbs=round(clicks * 0.1),
                    orders=round(clicks * 0.04),
                    spend=spend,
                    currency=CURRENCY,
                )
            )
    return rows


async def _seed_test(session: AsyncSession, workspace_id: uuid.UUID, plan: _Plan) -> int:
    """Write one test with its photos, rotation history and counters."""
    sku = SKU_BY_NM[plan.nm_id]
    test = AbTest(
        workspace_id=workspace_id,
        nm_id=plan.nm_id,
        vendor_code=sku.vendor_code,
        name=plan.name,
        status=plan.status.value,
        trigger_mode=plan.trigger.value,
        slot_minutes=plan.slot_minutes,
        started_at=plan.started,
        created_at=plan.created,
    )
    session.add(test)
    await session.flush()

    store = build_media_store(settings)
    variants: list[AbTestVariant] = []
    for position, (letter, backdrop, garment, _) in enumerate(_LOOKS[: plan.variants]):
        stored = await store.save(
            content=placeholder_photo(letter, backdrop, garment),
            content_type="image/jpeg",
            test_id=test.id,
        )
        variants.append(
            AbTestVariant(
                test_id=test.id,
                position=position,
                image_path=stored.relative_path,
                image_sha256=stored.sha256,
                content_type="image/jpeg",
                original_filename=f"demo-{letter.lower()}.jpg",
                is_original=position == 0,
            )
        )
    session.add_all(variants)
    await session.flush()

    rows: list[VariantExposure | VariantStatWindow | AbTestCampaign] = []
    clock = plan.started
    for index in range(plan.exposures):
        assert clock is not None
        variant = variants[index % len(variants)]
        ends = clock + timedelta(minutes=plan.slot_minutes)
        rows.append(
            VariantExposure(
                test_id=test.id,
                variant_id=variant.id,
                activated_at=clock,
                deactivated_at=ends,
                published_at=clock + timedelta(minutes=1),
                round_number=index // len(variants) + 1,
            )
        )
        rows.extend(_windows(test, variant, _LOOKS[variant.position][3], clock, plan))
        test.active_variant_id = variant.id
        clock = ends
    if plan.exposures:
        for campaign in _campaigns_for(plan.nm_id):
            rows.append(
                AbTestCampaign(
                    test_id=test.id,
                    campaign_id=campaign.campaign_id,
                    name=campaign.name,
                    kind=_kind(campaign),
                    first_seen_at=plan.started,
                    last_seen_at=clock,
                )
            )
    if plan.status is AbTestStatus.CANCELLED:
        # "Finish" keeps the best photo on the card and stamps both ends.
        test.active_variant_id = variants[1].id
        test.finished_at = test.stopped_at = clock
    session.add_all(rows)
    await session.flush()
    return 1 + len(variants) + len(rows)


async def seed_ab_tests(session: AsyncSession, workspace_id: uuid.UUID, today: date) -> int:
    """Write every demo test. Returns rows written."""
    written = 0
    for plan in _plans(today):
        written += await _seed_test(session, workspace_id, plan)
    return written
