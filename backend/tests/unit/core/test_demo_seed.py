"""The demo shop's figures: stable from day to day, and consistent across tables.

`make demo` re-seeds on every run, re-dated to the calendar. What makes that
safe to show is pinned here, on the pure simulation that every table is filled
from — no database involved:

* a day's numbers depend on the date, not on the day the seed ran, so a re-seed
  tomorrow does not rewrite the history a viewer has already seen;
* the tables agree with each other — the funnel contains its ads, the
  settlement satisfies WB's payout identity and each report's stated total —
  because a demo whose screens contradict each other demonstrates the wrong
  thing.
"""

from __future__ import annotations

import itertools
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest

from scripts.seed_demo import settlement
from scripts.seed_demo import simulation as sim
from scripts.seed_demo.catalogue import (
    CAMPAIGNS,
    NM_ID_BASE,
    SKU_BY_NM,
    SKUS,
    DemoCampaign,
    DemoSku,
)
from scripts.seed_demo.economics import sale_amounts

_TODAY = date(2026, 10, 22)  # a Thursday
_WORKSPACE = uuid.UUID("019f657a-0000-7000-8000-00000000de00")


def test_a_settled_day_reads_the_same_whichever_day_the_seed_runs() -> None:
    """Re-seeding a week later leaves an old day's funnel exactly as it was."""
    day = _TODAY - timedelta(days=30)

    seeded_today = [sim.funnel_day(sku, day, _TODAY) for sku in SKUS]
    seeded_next_week = [sim.funnel_day(sku, day, _TODAY + timedelta(days=7)) for sku in SKUS]

    assert seeded_today == seeded_next_week


def test_a_young_day_has_no_refusals_yet() -> None:
    """Inside WB's maturity window a day's outcome is still open, as WB reports it."""
    young = [sim.funnel_day(sku, _TODAY - timedelta(days=2), _TODAY) for sku in SKUS]
    mature = [sim.funnel_day(sku, _TODAY - timedelta(days=10), _TODAY) for sku in SKUS]

    assert all(day.cancels is None for day in young)
    assert all(day.cancels is not None for day in mature)


@pytest.mark.parametrize("campaign", CAMPAIGNS, ids=lambda c: f"campaign-{c.campaign_id % 100}")
def test_the_funnel_contains_the_traffic_its_campaigns_bought(campaign: DemoCampaign) -> None:
    """An article's opens and orders include its ads' clicks and orders."""
    sku = SKU_BY_NM[campaign.nm_id]
    days = sim.window(_TODAY - timedelta(days=1), 30)

    totals = [sim.demand(sku, day, _TODAY) for day in days]

    for day, (opens, _, orders) in zip(days, totals, strict=True):
        ads = [ad for ad in sim.ad_days(day, _TODAY) if ad.nm_id == sku.nm_id]
        assert opens >= sum(ad.clicks for ad in ads)
        assert orders >= sum(ad.orders for ad in ads)


@pytest.mark.parametrize("sku", SKUS, ids=lambda s: s.vendor_code)
def test_every_sale_satisfies_wbs_payout_identity(sku: DemoSku) -> None:
    """payout = paid − commission − its VAT − acquiring, to WB's half a kopeck."""
    days = [_TODAY - timedelta(days=offset) for offset in range(0, 60, 7)]

    sales = [sale_amounts(sku, day) for day in days]

    for amounts in sales:
        rebuilt = amounts.paid - amounts.commission - amounts.commission_vat - amounts.acquiring
        assert abs(rebuilt - amounts.payout) < Decimal("0.005")
        assert amounts.paid < amounts.seller_price < amounts.list_price


def test_the_reports_are_whole_wb_periods_ending_before_the_current_one() -> None:
    """Mon–Sun cut at month ends, contiguous, the newest ended before today's began."""
    reports = settlement.periods(_TODAY)

    assert reports[0].date_to == date(2026, 10, 18)
    for newer, older in itertools.pairwise(reports):
        assert older.date_to + timedelta(days=1) == newer.date_from
    for period in reports:
        assert period.date_from.month == period.date_to.month
        assert (period.date_to - period.date_from).days <= 6


def test_each_report_states_the_payout_its_rows_add_up_to(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WB's own total on the header equals Σ payout, refunds negative — the ledger check."""
    monkeypatch.setattr(settlement, "REPORTS", 2)  # two weeks prove it; nine are slow

    headers, rows = settlement.settlement_rows(_WORKSPACE, _TODAY)

    for header in headers:
        own = [row for row in rows if row["report_id"] == header["report_id"]]
        summed = sum(
            (-r["ppvz_for_pay"] if r["doc_type_name"] == "Возврат" else r["ppvz_for_pay"])
            for r in own
        )
        assert summed == header["wb_for_pay_sum"]
        assert all(header["date_from"] <= r["rr_dt"] <= header["date_to"] for r in own)


def test_settlement_rows_name_only_demo_articles(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every row is the demo's or the account's: no id WB could have issued to a real card."""
    monkeypatch.setattr(settlement, "REPORTS", 1)

    _, rows = settlement.settlement_rows(_WORKSPACE, _TODAY)

    assert {row["nm_id"] for row in rows} == {0} | {sku.nm_id for sku in SKUS}
    assert all(sku.nm_id > NM_ID_BASE for sku in SKUS)
