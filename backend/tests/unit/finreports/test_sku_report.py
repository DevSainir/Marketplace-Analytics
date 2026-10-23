"""Unit tests for the per-SKU P&L composition (the "By SKU" cut).

Same discipline as ``test_pnl_statement.py``: a synthetic 28-day window
(2026-08-03..2026-08-30) for an invented SKU, nm 900000101, built from round
numbers so every expected figure can be worked out by hand; the window total is
the exact sum of its rows, so a refactor cannot quietly redefine a line.

What earns a test here is everything that would fail *plausibly*: Σ rows +
unallocated must equal the window total (account-level money is never smeared
over SKUs); an uncosted SKU's profit is ``None``, never a number that pretends
the goods were free; a column with no source coverage (orders, advertising) is
``None``, never 0; refund-only windows give negative units and COGS, not clamps.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.modules.finreports.repos import SettlementAggregate
from src.modules.finreports.schemas.sku_report import SkuPenalty
from src.modules.finreports.services.pnl import build_sku_report, build_sku_row
from src.modules.finreports.services.pnl.sku_report import UNALLOCATED_NAME, build_dashboard


def _aggregate(**overrides: object) -> SettlementAggregate:
    """A per-SKU aggregate; defaults are nm 900000101's synthetic 28-day sums."""
    values: dict[str, object] = {
        "key": 900000101,
        "label": "m-trx01-blk",
        "date_from": date(2026, 8, 3),
        "date_to": date(2026, 8, 30),
        "currency": "KGS",
        "subject_name": "Trousers",
        "brand_name": "NORTH LINE",
        "sold_units": 800,
        "returned_units": 80,
        "sales_gross": Decimal("2000000.00"),
        "returns_gross": Decimal("200000.00"),
        "sales_before_spp": Decimal("2400000.00"),
        "returns_before_spp": Decimal("240000.00"),
        "payout_sales": Decimal("1600000.00"),
        "payout_returns": Decimal("160000.00"),
        "payout_other": Decimal("0"),
        "wb_commission_reported": Decimal("0"),
        "wb_commission_vat": Decimal("0"),
        "wb_reward": Decimal("0"),
        "acquiring_withheld": Decimal("0"),
        "acquiring_billed_apart": Decimal("0"),
        "agency_vat": Decimal("0"),
        "logistics_forward": Decimal("200000.00"),
        "logistics_return": Decimal("48000.00"),
        "logistics_unlegged": Decimal("0"),
        "storage": Decimal("0"),
        "acceptance": Decimal("0"),
        "penalties": Decimal("2400.00"),
        "deductions": Decimal("0"),
        "additional_payments": Decimal("0"),
        "rebill_logistic_cost": Decimal("0"),
        "advertising": Decimal("0"),
        "rows": 6400,
        "delivered_units": 2400,
    }
    values.update(overrides)
    return SettlementAggregate(**values)  # type: ignore[arg-type]


def _row(**kwargs: object):
    """Build one row with the cross-module inputs defaulted to "covered"."""
    defaults: dict[str, object] = {
        "nm_id": 900000101,
        "sa_name": "m-trx01-blk",
        "orders": 2600,
        "buyouts": (720, 960),
        "cost_price": Decimal("650"),
        "advertising": Decimal("180000.00"),
        "ad_bonus": Decimal("0"),
        "penalties": [],
    }
    defaults.update(kwargs)
    return build_sku_row(_aggregate(), **defaults)  # type: ignore[arg-type]


class TestSkuRow:
    """The single-row arithmetic."""

    def test_the_payout_is_net_of_the_skus_own_withholdings(self) -> None:
        """payout − logistics − fines, exactly the reference workbook's column."""
        row = _row()

        payout_goods = Decimal("1600000.00") - Decimal("160000.00")
        withheld = Decimal("200000.00") + Decimal("48000.00") + Decimal("2400.00")

        assert row.payout_for_goods == payout_goods
        assert row.payout_net == payout_goods - withheld

    def test_net_profit_subtracts_cogs_and_advertising_from_the_payout(self) -> None:
        """Net profit = payout − cost of goods − advertising."""
        row = _row()

        cogs = Decimal("650") * (800 - 80)

        assert row.cogs == cogs
        assert row.net_profit == row.payout_net - cogs - Decimal("180000.00")

    def test_percentages_are_shares_of_net_sales_at_the_seller_s_price(self) -> None:
        """Logistics, DRR and margin are % of "Sales": seller's price before SPP, net of returns.

        Net of returns, as the seller's workbook does it. The base was "Paid"
        (after SPP) until 2026-09-26, while the dashboard card used "Sales", so
        one page gave two logistics shares. SPP is WB's discount and moves every
        week: on the paid base a seller's logistics share rose whenever WB raised
        it, with nothing about the seller's costs changed.
        """
        row = _row()

        base = row.revenue_seller_price

        def share(part: Decimal) -> Decimal:
            return (part / base * 100).quantize(Decimal("0.01"))

        assert row.logistics_pct == share(row.logistics_total)
        assert row.advertising is not None
        assert row.advertising_pct == share(row.advertising)
        assert row.net_profit is not None
        assert row.net_profit_pct == share(row.net_profit)

    def test_average_cheque_is_net_revenue_per_bought_out_unit(self) -> None:
        """Average cheque = (sales − returns) ÷ bought-out units."""
        row = _row()
        net_units = 800 - 80

        assert row.average_cheque == (row.revenue_paid / net_units).quantize(Decimal("0.01"))

    def test_roi_is_profit_over_cost(self) -> None:
        """Profit-based, per the seller's choice."""
        row = _row()

        assert row.net_profit is not None
        assert row.cogs is not None
        assert row.roi_pct == (row.net_profit / row.cogs * 100).quantize(Decimal("0.01"))

    def test_roi_is_none_without_a_cost(self) -> None:
        """No cost → no profit → no ROI."""
        uncosted = _row(cost_price=None)

        assert uncosted.roi_pct is None

    def test_buyout_is_wbs_own_percentage_from_the_funnel(self) -> None:
        """Buyout rate = buyouts ÷ (buyouts + refusals) by order date, as in WB's portal."""
        row = _row(buyouts=(720, 960))

        assert (row.buyout_units, row.decided_units) == (720, 960)
        assert row.buyout_pct == Decimal("75.00")

    def test_buyout_is_none_when_no_order_has_been_decided(self) -> None:
        """No decided order is "unknown", not a 0 % or an infinite buyout."""
        assert _row(buyouts=(0, 0)).buyout_pct is None

    def test_buyout_is_unknown_without_funnel_coverage(self) -> None:
        """Without the funnel there is no buyout at all, not a zero one."""
        row = _row(buyouts=None)

        assert row.buyout_pct is None
        assert row.decided_units is None

    def test_an_uncosted_sku_reports_no_profit_at_all(self) -> None:
        """``None``, not «profit assuming the goods were free»."""
        row = _row(cost_price=None)

        assert row.cogs is None
        assert row.net_profit is None
        assert row.net_profit_pct is None

    def test_missing_source_history_is_none_never_zero(self) -> None:
        """ "There were no orders" and "orders are unknown" must not look alike."""
        row = _row(orders=None, advertising=None)

        assert row.orders_units is None
        assert row.advertising is None
        assert row.advertising_pct is None

    def test_drr_is_withheld_when_returns_outweigh_sales(self) -> None:
        """Advertising over a negative revenue is a negative DRR — meaningless, so none."""
        row = build_sku_row(
            _aggregate(sales_before_spp=Decimal("60000"), returns_before_spp=Decimal("75000")),
            nm_id=900000101,
            sa_name="m-trx01-blk",
            orders=10,
            buyouts=(720, 960),
            cost_price=Decimal("650"),
            advertising=Decimal("1500"),
            ad_bonus=Decimal("0"),
            penalties=[],
        )

        assert row.revenue_seller_price < 0
        assert row.advertising_pct is None

    def test_a_refund_only_window_goes_negative_instead_of_clamping(self) -> None:
        """Refund-only report x SKU cells are common enough in real reports to pin."""
        row = _row(
            **{
                "cost_price": Decimal("650"),
            }
        )
        refund_only = build_sku_row(
            _aggregate(
                sold_units=0,
                returned_units=2,
                sales_gross=Decimal("0"),
                returns_gross=Decimal("4800.00"),
                payout_sales=Decimal("0"),
                payout_returns=Decimal("3840.00"),
            ),
            nm_id=900000101,
            sa_name="m-trx01-blk",
            orders=0,
            buyouts=(0, 0),
            cost_price=Decimal("650"),
            advertising=Decimal("0"),
            ad_bonus=Decimal("0"),
            penalties=[],
        )

        assert row.cogs is not None  # sanity on the base case
        assert row.cogs > 0
        assert refund_only.cogs == Decimal("650") * -2
        assert refund_only.net_profit is not None
        assert refund_only.revenue_paid == Decimal("-4800.00")


#: The window total aggregate paired with :func:`_window`, exposed so the
#: dashboard tests can read its account-level deductions. Every figure is the
#: exact sum of the two SKUs and the account bucket below.
_TOTAL = _aggregate(
    key=None,
    label="",
    sold_units=920,
    returned_units=92,
    sales_gross=Decimal("2240000.00"),
    returns_gross=Decimal("224000.00"),
    sales_before_spp=Decimal("2688000.00"),
    returns_before_spp=Decimal("268800.00"),
    payout_sales=Decimal("1792000.00"),
    payout_returns=Decimal("179200.00"),
    logistics_forward=Decimal("232000.00"),
    logistics_return=Decimal("54000.00"),
    penalties=Decimal("2400.00"),
    storage=Decimal("14000.00"),
    # The whole of that deduction IS the "WB Promotion" invoice — the account
    # bucket's only charge besides storage.
    deductions=Decimal("165000.00"),
    advertising=Decimal("165000.00"),
    rows=7380,
    delivered_units=2760,
)


def _window(
    excluded: set[int] | None = None,
    photos: dict[int, str] | None = None,
    ad_bonus: dict[int, Decimal] | None = None,
    ad_spend: dict[int, Decimal] | None = None,
    ad_covered: bool = True,
):
    """Two SKUs + the account bucket, with a matching window total."""
    sku_a = _aggregate()
    sku_b = _aggregate(
        key=900000102,
        label="m-trx01-chk",
        sold_units=120,
        returned_units=12,
        sales_gross=Decimal("240000.00"),
        returns_gross=Decimal("24000.00"),
        sales_before_spp=Decimal("288000.00"),
        returns_before_spp=Decimal("28800.00"),
        payout_sales=Decimal("192000.00"),
        payout_returns=Decimal("19200.00"),
        logistics_forward=Decimal("32000.00"),
        logistics_return=Decimal("6000.00"),
        penalties=Decimal("0"),
        rows=960,
        delivered_units=360,
    )
    account = _aggregate(
        key=0,
        label="",
        sold_units=0,
        returned_units=0,
        sales_gross=Decimal("0"),
        returns_gross=Decimal("0"),
        sales_before_spp=Decimal("0"),
        returns_before_spp=Decimal("0"),
        payout_sales=Decimal("0"),
        payout_returns=Decimal("0"),
        logistics_forward=Decimal("0"),
        logistics_return=Decimal("0"),
        penalties=Decimal("0"),
        storage=Decimal("14000.00"),
        deductions=Decimal("165000.00"),
        advertising=Decimal("165000.00"),
        rows=20,
        delivered_units=0,
    )
    return build_sku_report(
        sku_aggregates=[sku_b, account, sku_a],
        total_aggregate=_TOTAL,
        costs={900000101: Decimal("650"), 900000102: Decimal("540")},
        orders={900000101: 2600, 900000102: 400},
        buyouts={900000101: (600, 800), 900000102: (90, 120)},
        ad_spend=(
            (ad_spend if ad_spend is not None else {900000101: Decimal("180000.00")})
            if ad_covered
            else None
        ),
        ad_bonus=(
            ({900000101: Decimal("0")} if ad_bonus is None else ad_bonus) if ad_covered else None
        ),
        penalties=[
            (900000101, "Discrepancies found in the product card", Decimal("1800.00")),
            (900000101, "Paid storage of returns at a pickup point", Decimal("600.00")),
        ],
        excluded=excluded,
        photos=photos,
    )


class TestSkuReport:
    """The report assembly and its reconciliation frame."""

    def _report(self):
        """Two SKUs + the account bucket, with a matching window total."""
        return _window()

    def test_rows_plus_unallocated_reconcile_to_the_totals_exactly(self) -> None:
        """The invariant the report exists to keep — no tolerance."""
        rows, unallocated, totals = self._report()

        assert unallocated is not None
        for field in ("payout_net", "sales_amount", "logistics_total", "penalties_total"):
            summed = sum((getattr(r, field) for r in rows), Decimal(0)) + getattr(
                unallocated, field
            )
            assert summed == getattr(totals, field), field

    def test_account_level_money_lands_in_the_unallocated_bucket(self) -> None:
        """Storage and the advertising invoices have no nm_id — no smearing."""
        _rows, unallocated, _totals = self._report()

        assert unallocated is not None
        assert unallocated.sa_name == UNALLOCATED_NAME
        assert unallocated.payout_net == -(Decimal("14000.00") + Decimal("165000.00"))
        assert unallocated.orders_units is None
        assert unallocated.advertising is None

    def test_rows_are_sorted_by_net_revenue_descending(self) -> None:
        """The biggest SKU first — the order a seller scans in."""
        rows, _unallocated, _totals = self._report()

        assert [r.nm_id for r in rows] == [900000101, 900000102]

    def test_a_sku_without_ads_shows_zero_when_coverage_exists(self) -> None:
        """Coverage exists and this SKU ran nothing: that is a true zero."""
        rows, _unallocated, _totals = self._report()

        chk = next(r for r in rows if r.nm_id == 900000102)

        assert chk.advertising == Decimal(0)

    def test_penalty_categories_stay_with_their_sku(self) -> None:
        """The category is what makes a fine actionable."""
        rows, _unallocated, totals = self._report()

        blk = next(r for r in rows if r.nm_id == 900000101)

        assert [p.reason for p in blk.penalties] == [
            "Discrepancies found in the product card",
            "Paid storage of returns at a pickup point",
        ]
        assert isinstance(totals.penalties[0], SkuPenalty)

    def test_totals_cogs_is_the_sum_of_costed_rows(self) -> None:
        """No average cost exists across SKUs; the total is Σ of the parts."""
        rows, _unallocated, totals = self._report()

        assert totals.cogs == sum((r.cogs for r in rows if r.cogs is not None), Decimal(0))

    def test_the_totals_charge_wbs_invoice_once(self) -> None:
        """WB bills the same advertising two ways; "Total" charges the invoice.

        The weekly "WB Promotion" invoice is withheld inside the payout,
        and the Promotion API reports the same spend dated to the days the ads
        ran. Subtracting the burn from a payout already net of the invoice
        charges it twice, and the profit comes out short by the whole
        advertising budget. Until 2026-10-02 the total swapped
        the invoice for the burn; by the owner's decision the total is now WB's
        invoice, so the payout already carries the whole advertising charge.
        """
        _rows, _unallocated, totals = self._report()

        assert totals.net_profit == totals.payout_net - totals.cogs
        assert totals.advertising_cash is not None
        assert totals.advertising_cash > 0
        assert totals.advertising == totals.advertising_cash + (totals.ad_bonus or Decimal(0))

    def test_without_ad_coverage_the_total_is_still_the_invoice(self) -> None:
        """The invoice is WB's own figure; it does not need the burn to be known."""
        _rows, _unallocated, covered = _window()
        _rows, _unallocated, totals = _window(ad_covered=False)

        assert totals.advertising_cash == covered.advertising_cash
        assert totals.net_profit == totals.payout_net - totals.cogs

    def test_a_mark_only_flags_the_row_it_never_touches_the_totals(self) -> None:
        """The reconciled totals stay full; only build_dashboard sees the mark."""
        rows, _unallocated, totals = _window(excluded={900000102})

        assert next(r for r in rows if r.nm_id == 900000102).is_excluded is True
        assert next(r for r in rows if r.nm_id == 900000101).is_excluded is False
        # Totals unchanged vs the unmarked window.
        assert totals.payout_net == _window()[2].payout_net


class TestDashboard:
    """The exclusion-aware dashboard KPIs."""

    def test_with_nothing_marked_the_dashboard_equals_the_full_totals(self) -> None:
        """So "Sales" matches WB and "Payout" matches "Total payout"."""
        rows, _unallocated, totals = _window()

        dash = build_dashboard(rows=rows, totals=totals, total_aggregate=_TOTAL)

        assert dash.excluded_count == 0
        assert dash.sales == totals.revenue_seller_price  # "Sales" = seller price
        assert dash.paid == totals.revenue_paid  # qualifier: what buyers paid
        assert dash.logistics == totals.logistics_total
        assert dash.payout_net == totals.payout_net
        assert dash.cogs == totals.cogs

    def test_a_marked_sku_leaves_all_four_per_sku_cards(self) -> None:
        """Each card drops exactly that SKU's share; the overall total shrinks."""
        rows, _unallocated, totals = _window(excluded={900000102})
        marked = next(r for r in rows if r.nm_id == 900000102)

        dash = build_dashboard(rows=rows, totals=totals, total_aggregate=_TOTAL)

        assert dash.excluded_count == 1
        assert dash.sales == totals.revenue_seller_price - marked.revenue_seller_price
        assert dash.paid == totals.revenue_paid - marked.revenue_paid
        assert dash.logistics == totals.logistics_total - marked.logistics_total
        assert dash.payout_net == totals.payout_net - marked.payout_net
        assert marked.cogs is not None
        assert dash.cogs == totals.cogs - marked.cogs

    def test_account_level_other_deductions_never_move_with_a_mark(self) -> None:
        """The "Other deductions" line has no nm_id, so no SKU mark can touch it."""
        rows, _unallocated, totals = _window(excluded={900000102})

        dash = build_dashboard(rows=rows, totals=totals, total_aggregate=_TOTAL)

        assert dash.other_deductions == _TOTAL.deductions
        assert dash.advertising == _TOTAL.advertising


class TestThumbnails:
    """The card image the "By SKU" table shows beside each article."""

    PHOTO = "https://basket-01.wbbasket.ru/vol9000/part900000/900000101/images/big/1.webp"

    def test_a_catalogued_sku_carries_its_card_photo(self) -> None:
        """The thumbnail reaches the row it belongs to, keyed by nm_id."""
        rows, _unallocated, _totals = _window(photos={900000101: self.PHOTO})

        assert next(r for r in rows if r.nm_id == 900000101).photo_url == self.PHOTO

    def test_a_sku_the_catalogue_does_not_know_still_gets_its_row(self) -> None:
        """A settlement SKU with no card is thumbnail-less, never dropped.

        A workspace can be settled for a SKU before its first catalogue harvest
        has run. Losing the row would lose real money off a reconciled report;
        losing the picture costs nothing.
        """
        rows, _unallocated, _totals = _window(photos={900000101: self.PHOTO})

        uncatalogued = next(r for r in rows if r.nm_id == 900000102)
        assert uncatalogued.photo_url is None

    def test_the_account_level_rows_are_not_a_product_and_show_no_photo(self) -> None:
        """The "Not tied to a SKU" bucket and "Total" span many SKUs, so neither has one.

        Both are built with ``nm_id = 0``; a catalogue that ever held a card
        under that id would otherwise put a random product's photo on the
        totals row.
        """
        _rows, unallocated, totals = _window(photos={0: self.PHOTO, 900000101: self.PHOTO})

        assert unallocated is not None
        assert unallocated.photo_url is None
        assert totals.photo_url is None
