"""Bonuses: the advertising WB paid for, and what it is allowed to move.

WB funds part of a seller's advertising from a bonus pool (cashback, up to 50 %
of a charge). Those impressions are in ``fullstats`` like any other and never
reach the settlement report at all — a bonus write-off carries no invoice
document — so until 2026-09-15 every per-SKU DRR, ROI and profit counted WB's
money as the seller's. The error was large where it was found: a sizeable share
of the spend was WB-funded, and a SKU could read a deeply negative ROI while its
cash figure was positive.

The figures below are a synthetic SKU in that shape — nm 900000101, with 60 000
of 180 000 KGS of advertising WB-funded. What earns a test here is each way the
correction could go wrong:

* subtracting the bonus twice (a negative magnitude, then subtracted again);
* letting it reach the payout, which is WB's settled figure and the anchor
  of Σ rows + unallocated = totals — and which a cashback never touched;
* reading «ledger not harvested» as «no bonuses», i.e. ``None`` as ``0``;
* letting a window-edge charge exceed its spend and print a negative cost.

The allocation onto SKUs is SQL and is tested in
``tests/integration/monitoring/test_ad_bonus_allocation.py``; this file is the
arithmetic that consumes it.
"""

from __future__ import annotations

from decimal import Decimal

from tests.unit.finreports.test_sku_report import _row, _window


def _report_with_bonus(ad_bonus: dict[int, Decimal]):
    """The two-SKU window with an explicit per-SKU bonus mapping."""
    return _window(ad_bonus=ad_bonus)


class TestAdvertisingBonus:
    """Bonuses: the share of the ad spend WB paid, and what it may move.

    Every figure below is the synthetic shape of nm 900000101, where WB funded
    60 000 of 180 000 KGS of advertising. The point of the block is that the
    bonus reaches profit and ROI — and reaches nothing else.
    """

    def test_the_advertising_column_stays_gross_of_the_bonus(self) -> None:
        """The "Advertising" column keeps showing what WB's own seller portal shows.

        The seller reconciles that column against WB by eye; netting the bonus
        into it would make it disagree with the portal and hide the deduction
        the new column exists to show.
        """
        row = _row(advertising=Decimal("180000"), ad_bonus=Decimal("60000"))

        assert row.advertising == Decimal("180000")
        assert row.ad_bonus == Decimal("60000")
        assert row.advertising_cash == Decimal("120000")

    def test_the_bonus_is_reported_positive_and_subtracted_exactly_once(self) -> None:
        """The API carries a magnitude; the sign is applied where it composes.

        A negative `ad_bonus` would be subtracted twice — once by the sign and
        once by the arithmetic — which reads as a plausible extra profit.
        """
        row = _row(advertising=Decimal("180000"), ad_bonus=Decimal("60000"))

        assert row.ad_bonus > 0
        assert row.advertising - row.ad_bonus == row.advertising_cash

    def test_profit_and_roi_move_to_the_money_actually_spent(self) -> None:
        """The figures the seller decides on use the cash cost."""
        gross = _row(advertising=Decimal("180000"), ad_bonus=Decimal("0"))
        funded = _row(advertising=Decimal("180000"), ad_bonus=Decimal("60000"))

        assert funded.net_profit == gross.net_profit + Decimal("60000")
        assert funded.roi_pct is not None
        assert gross.roi_pct is not None
        assert funded.roi_pct > gross.roi_pct

    def test_the_payout_is_untouched_by_the_bonus(self) -> None:
        """The settled payout is WB's own figure and the reconciliation anchor.

        A cashback write-off never enters the settlement at all (it carries no
        invoice document), so there is nothing in the payout for it to
        change — and moving it would break Σ rows + unallocated = totals.
        """
        gross = _row(advertising=Decimal("180000"), ad_bonus=Decimal("0"))
        funded = _row(advertising=Decimal("180000"), ad_bonus=Decimal("60000"))

        assert funded.payout_net == gross.payout_net
        assert funded.payout_for_goods == gross.payout_for_goods
        assert funded.revenue_paid == gross.revenue_paid

    def test_a_bonus_larger_than_the_spend_cannot_make_advertising_negative(self) -> None:
        """A write-off dated inside a window whose impressions fell outside it.

        The ledger and fullstats are dated differently (charge day vs display
        day), so at a window edge the bonus can arrive without its spend. The
        clamp keeps that from printing a negative advertising cost — and the
        REPORTED bonus is the clamped one, so "Advertising" − "Bonuses" still equals
        the cash cost on screen.
        """
        row = _row(advertising=Decimal("800"), ad_bonus=Decimal("2000"))

        assert row.advertising_cash == Decimal("0")
        assert row.ad_bonus == Decimal("800")
        assert row.advertising - row.ad_bonus == row.advertising_cash

    def test_no_ledger_coverage_reports_none_not_zero(self) -> None:
        """ "We don't know" must not be rendered as "there were no bonuses".

        A zero would quietly lower nothing and look like a fact; ``None`` says
        the ledger has not been harvested for the window.
        """
        row = _row(advertising=Decimal("180000"), ad_bonus=None)

        assert row.ad_bonus is None
        assert row.advertising_cash == Decimal("180000")

    def test_without_advertising_coverage_the_bonus_is_none_too(self) -> None:
        """A bonus against unknown spend is a number with nothing to qualify."""
        row = _row(advertising=None, ad_bonus=Decimal("60000"))

        assert row.advertising is None
        assert row.ad_bonus is None
        assert row.advertising_cash is None

    def test_the_account_level_bucket_carries_no_bonus(self) -> None:
        """nm_id 0 is WB's own money, not a product: ads are not its concept."""
        rows, unallocated, _ = _report_with_bonus({900000101: Decimal("60000")})

        assert unallocated is not None
        assert unallocated.ad_bonus is None
        assert unallocated.advertising_cash is None
        assert any(r.ad_bonus == Decimal("60000") for r in rows)

    def test_the_totals_row_shows_the_bonus_beside_the_invoice(self) -> None:
        """The totals row charges WB's invoice, which never carried the bonus in the first place.

        A bonus write-off has no invoice document, so the invoice is already the
        cash part; the bonus is added to "Advertising" as the WB-funded share and
        moves no profit.
        """
        _, _, gross = _report_with_bonus({})
        _, _, funded = _report_with_bonus({900000101: Decimal("60000")})

        assert funded.ad_bonus == Decimal("60000")
        assert funded.advertising_cash == gross.advertising_cash
        assert funded.advertising == gross.advertising + Decimal("60000")
        assert funded.net_profit == gross.net_profit
        assert funded.payout_net == gross.payout_net
