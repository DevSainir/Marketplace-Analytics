"""Which zone a campaign-day's money lands in — the «На что ушли» table's rows.

The rules mirror the monitoring matrix's ``_classify``; these tests pin the
money side so a campaign cannot sit in one zone on the matrix and another here.
"""

from __future__ import annotations

from decimal import Decimal

from src.modules.advertising.services.zones import zone_legs
from src.modules.monitoring.contract import AdCampaignMeta


def _meta(payment: str, bid: str | None, *, search: bool, shelves: bool) -> AdCampaignMeta:
    return AdCampaignMeta(1, payment, bid, search, shelves)


def test_a_manual_search_campaign_sheds_its_remainder_into_the_catalogue() -> None:
    """WB «поисковые» also deliver in the catalogue: what normquery does not see is «Каталог»."""
    meta = _meta("cpm", "manual", search=True, shelves=False)

    legs = zone_legs(meta, Decimal("100"), Decimal("88"))

    assert legs == [("cpm_manual_search", Decimal("88")), ("cpm_manual_catalog", Decimal("12"))]


def test_a_manual_search_day_without_a_slice_stays_in_search() -> None:
    """A missing normquery row must not push ~90 % of a search campaign into the catalogue."""
    meta = _meta("cpm", "manual", search=True, shelves=False)

    legs = zone_legs(meta, Decimal("100"), None)

    assert legs == [("cpm_manual_search", Decimal("100"))]


def test_a_unified_campaign_splits_into_search_and_shelves() -> None:
    """Единая ставка: the slice is «Поиск», the remainder «Полки» (catalogue inside it)."""
    meta = _meta("cpm", "unified", search=True, shelves=True)

    legs = zone_legs(meta, Decimal("100"), Decimal("30"))

    assert legs == [("cpm_unified_search", Decimal("30")), ("cpm_unified_shelves", Decimal("70"))]


def test_cpc_is_its_own_group_whatever_the_bid_type() -> None:
    """Paid per click, its money is not comparable with a CPM campaign's."""
    meta = _meta("cpc", "unified", search=True, shelves=True)

    legs = zone_legs(meta, Decimal("100"), Decimal("40"))

    assert legs == [("cpc_search", Decimal("40")), ("cpc_shelves", Decimal("60"))]


def test_a_slice_above_the_total_never_prints_a_negative_remainder() -> None:
    """The two feeds are harvested at different times; the slice is clamped at the total."""
    meta = _meta("cpm", "unified", search=True, shelves=True)

    legs = zone_legs(meta, Decimal("100"), Decimal("100.40"))

    assert legs == [("cpm_unified_search", Decimal("100")), ("cpm_unified_shelves", Decimal("0"))]


def test_a_campaign_whose_settings_never_synced_is_unclassified_not_dropped() -> None:
    """Its money still counts toward the total; it just has no zone row."""
    legs = zone_legs(None, Decimal("55"), Decimal("10"))

    assert legs == [("unclassified", Decimal("55"))]
