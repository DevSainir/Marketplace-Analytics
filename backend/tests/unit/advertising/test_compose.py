"""The page's four cuts — headline, days, zones, articles — come from one set of rows.

The reason they must agree is the reader: "Total" in the article table, the
headline card and the sum of the chart are the same money, and any difference
between them reads as a bug in the report rather than as rounding.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.modules.advertising.services.compose import SaleDay, compose
from src.modules.monitoring.contract import (
    AdCampaignBonus,
    AdCampaignFacts,
    AdCampaignMeta,
    AdCampaignSearch,
    AdCampaignSpend,
    CatalogCard,
)

D1, D2, D3 = date(2026, 9, 14), date(2026, 9, 15), date(2026, 9, 16)
SEARCH_CAMPAIGN, UNIFIED_CAMPAIGN = 11, 22
NM_A, NM_B = 1001, 1002


def _facts() -> AdCampaignFacts:
    """Two campaigns over three days, a bonus charged in one batch on the second."""
    return AdCampaignFacts(
        campaigns=[
            AdCampaignMeta(SEARCH_CAMPAIGN, "cpm", "manual", True, False),
            AdCampaignMeta(UNIFIED_CAMPAIGN, "cpm", "unified", True, True),
        ],
        spend=[
            AdCampaignSpend(SEARCH_CAMPAIGN, D1, NM_A, Decimal("100")),
            AdCampaignSpend(SEARCH_CAMPAIGN, D2, NM_A, Decimal("100")),
            AdCampaignSpend(SEARCH_CAMPAIGN, D2, NM_B, Decimal("50")),
            AdCampaignSpend(UNIFIED_CAMPAIGN, D3, NM_B, Decimal("33.33")),
        ],
        search=[
            AdCampaignSearch(SEARCH_CAMPAIGN, D1, Decimal("90")),
            AdCampaignSearch(SEARCH_CAMPAIGN, D2, Decimal("120")),
            AdCampaignSearch(UNIFIED_CAMPAIGN, D3, Decimal("11.11")),
        ],
        bonus=[AdCampaignBonus(SEARCH_CAMPAIGN, D2, Decimal("187.77"))],
    )


def _cards() -> list[CatalogCard]:
    return [
        CatalogCard(NM_A, "M-A", "", "", "Trousers", "X"),
        CatalogCard(NM_B, "M-B", "", "", "Jackets", "Y"),
    ]


def test_every_cut_sums_to_the_headline_spend_and_bonus() -> None:
    """Days, zones and articles each add up to the cards, to the kopeck."""
    page = compose(_facts(), sales=[], settled_to=None, catalog=_cards(), orders=None)

    for cut in (page.days, page.zones, page.skus):
        assert sum(row.spend for row in cut) == page.totals.spend == Decimal("283.33")
        assert sum(row.bonus for row in cut) == page.totals.bonus == Decimal("187.77")


def test_the_zone_split_follows_the_campaigns_placements() -> None:
    """A search-only manual campaign's remainder is the catalogue; a unified one's, the shelves."""
    page = compose(_facts(), sales=[], settled_to=None, catalog=_cards(), orders=None)

    zones = {row.zone: row.spend for row in page.zones}
    assert zones == {
        "cpm_manual_search": Decimal("210"),
        "cpm_manual_catalog": Decimal("40"),
        "cpm_unified_search": Decimal("11.11"),
        "cpm_unified_shelves": Decimal("22.22"),
    }


def test_drr_inputs_stop_where_the_settlement_does() -> None:
    """Spend after the last settled day has no sales to divide by, so it is not in the numerator."""
    sales = [SaleDay(NM_A, D1, Decimal("1000")), SaleDay(NM_B, D2, Decimal("500"))]

    page = compose(_facts(), sales=sales, settled_to=D2, catalog=_cards(), orders={NM_A: 7})

    assert page.totals.spend_settled == Decimal("250")
    # The 187.77 bonus was charged on D2, inside the settled span, so all of it
    # comes off DRR's numerator: the seller's own money is spend minus bonus.
    assert page.totals.bonus_settled == Decimal("187.77")
    assert page.totals.sales == Decimal("1500")
    assert [day.sales for day in page.days] == [Decimal("1000"), Decimal("500"), None]
    rows = {row.vendor_code: row for row in page.skus}
    assert rows["M-B"].spend_settled == Decimal("50")
    assert (rows["M-A"].orders, rows["M-B"].orders) == (7, 0)


def test_without_a_settlement_sales_are_unknown_rather_than_zero() -> None:
    """Sales not calculated yet must not read as no sales — DRR would show as infinite."""
    page = compose(_facts(), sales=[], settled_to=None, catalog=_cards(), orders=None)

    assert page.totals.sales is None
    assert all(row.sales is None for row in page.skus)
    assert all(row.orders is None for row in page.skus)


def test_an_articles_zones_add_up_to_its_row_to_the_kopeck() -> None:
    """The row's breakdown is the row: its zones sum to its spend and its bonus."""
    page = compose(_facts(), sales=[], settled_to=None, catalog=_cards(), orders=None)

    for row in page.skus:
        assert sum(zone.spend for zone in row.zones) == row.spend
        assert sum(zone.bonus for zone in row.zones) == row.bonus


def test_an_article_takes_its_share_of_each_zone_of_the_campaign_day() -> None:
    """M-B took a third of the search campaign's 15.09, so a third of each of its zones.

    That day the campaign spent 150 — 120 of it in search, 30 in the catalogue —
    of which M-B's 50: 40 in search and 10 in the catalogue. Its 16.09 is the
    unified campaign alone.
    """
    page = compose(_facts(), sales=[], settled_to=None, catalog=_cards(), orders=None)

    rows = {row.vendor_code: {zone.zone: zone.spend for zone in row.zones} for row in page.skus}
    assert rows["M-B"] == {
        "cpm_manual_search": Decimal("40"),
        "cpm_manual_catalog": Decimal("10"),
        "cpm_unified_search": Decimal("11.11"),
        "cpm_unified_shelves": Decimal("22.22"),
    }
    assert rows["M-A"] == {
        "cpm_manual_search": Decimal("170"),
        "cpm_manual_catalog": Decimal("30"),
    }
