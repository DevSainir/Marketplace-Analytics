"""Unit tests for the metrics-matrix builder: the reference two-campaign day.

The load-bearing rules, all exercised against one realistic scenario — a
unified campaign shown in BOTH its WB zones, a manual search campaign, and a
noise campaign that must be cut: «Доля трафика» normalized within each bid
type, ad revenue derived from the slice's own orders, ДРР against the
campaign's own buyouts, the funnel-backed «Общая»/«Органика» columns computed
over survivors only, and the lagged «Процент выкупа» window.

Edge cases around each rule live in the sibling ``test_matrix_*`` modules; the
row builders live in ``tests/support/matrix_rows.py``.
"""

from __future__ import annotations

from datetime import timedelta

from tests.support.matrix_rows import DAY1, _cell, _funnel_row, _matrix, _two_campaign_rows


def test_unified_shows_both_zones_and_manual_is_kept() -> None:
    """A surviving unified campaign keeps both WB zones; the manual one shows too."""
    rows = _two_campaign_rows()

    assert _cell(rows, "views", 0, "uni_search") == 30  # unified search slice shown
    assert _cell(rows, "views", 0, "uni_shelves") == 70
    assert _cell(rows, "views", 0, "manual_search") == 40
    assert _cell(rows, "views", 0, "manual_shelves") is None  # no such campaign


def test_traffic_share_normalized_within_bid_type() -> None:
    """«Доля трафика» sums to 100% within Единая and within Ручной separately."""
    rows = _two_campaign_rows()

    # Единая: 30 + 70 = 100 views -> 30% / 70%.
    assert _cell(rows, "traffic_share", 0, "uni_search") == 30.0
    assert _cell(rows, "traffic_share", 0, "uni_shelves") == 70.0
    # Ручной: the single manual campaign is 100% of its own type.
    assert _cell(rows, "traffic_share", 0, "manual_search") == 100.0


def test_ad_revenue_is_derived_from_the_slices_own_orders() -> None:
    """An ad zone's «Заказы, ₽» = ITS orders x the day's price — not WB's figure.

    WB reports no zone-attributed revenue (and none at all for a split
    campaign), so every ad bucket derives its own, split or not. The unified
    campaign took 2 orders, split 1/1 across its zones; the manual one took 1;
    the day's seller price is 50 000 ₽.
    """
    rows = _two_campaign_rows()

    assert _cell(rows, "order_sum", 0, "uni_search") == 50000
    assert _cell(rows, "order_sum", 0, "uni_shelves") == 50000
    assert _cell(rows, "order_sum", 0, "manual_search") == 50000
    # «Выкупы, ₽»: that revenue x the lagged «Процент выкупа» (40%).
    assert _cell(rows, "order_sum", 0, "uni_search") == 50000
    assert _cell(rows, "buyout_sum", 0, "uni_search") == 20000
    # ДРР от заказов is that zone's spend against the orders IT delivered.
    assert _cell(rows, "drr_orders", 0, "manual_search") == 4.0  # 2000 / 50000
    assert _cell(rows, "drr_orders", 0, "uni_search") == 3.0  # 1500 / 50000


def test_drr_sales_divides_campaign_spend_by_campaign_buyouts() -> None:
    """«ДРР от продаж» is campaign spend / the campaign's OWN buyout revenue.

    Never the SKU's whole-day volume: the unified campaign spent 5 000 ₽ (1 500
    search + 3 500 shelves) and delivered 2 orders, worth 2 x 50 000 x 40% =
    40 000 ₽ of buyouts -> 12.5%. Both of its zones carry that one number so
    the frontend can merge them; the manual campaign is judged on its own
    2 000 ₽ against 20 000 ₽ -> 10%.
    """
    rows = _two_campaign_rows()

    assert _cell(rows, "drr_sales", 0, "uni_search") == 12.5
    assert _cell(rows, "drr_sales", 0, "uni_shelves") == 12.5
    assert _cell(rows, "drr_sales", 0, "manual_search") == 10.0
    # The legacy «Каталог» zone stays empty, and «Общая» keeps its own
    # SKU-wide reading (all ad spend against the day's whole buyout value).
    assert _cell(rows, "drr_sales", 0, "uni_catalog") is None


def test_total_and_organic_use_survivors_only() -> None:
    """«Общая»/«Органика» count only the surviving campaigns (noise excluded)."""
    rows = _two_campaign_rows()

    # Ad roll-up = both survivors: 100 (unified) + 40 (manual) = 140 views, 7000₽
    # spend, 14 clicks. The unclassifiable noise (10 views / 5₽) is NOT counted.
    assert _cell(rows, "views", 0, "total") == 140
    assert _cell(rows, "spend", 0, "total") == 7000
    assert _cell(rows, "clicks", 0, "total") == 200  # funnel card opens
    # Organic = funnel - surviving ad. Ad clicks = 14 -> organic 200-14 = 186.
    assert _cell(rows, "clicks", 0, "organic") == 186
    assert _cell(rows, "carts", 0, "organic") == 13  # 20 - (3+2+2)
    assert _cell(rows, "orders", 0, "organic") == 7  # 10 - (1+1+1)


def test_total_cpm_is_the_days_bill_over_the_days_showings() -> None:
    """«CPM» in «Общая» is a ratio of sums, like the «CTR» row beside it.

    The two surviving campaigns spent 3 000 + 2 000 + 2 000 = 7 000 ₽ on
    60 + 40 + 40 = 140 показов, so the day cost 50 000 ₽ per thousand of them.
    Not the mean of the campaigns' own CPMs — that is the number this column
    used to withhold, and rightly, because a CPC campaign's is an artefact of
    per-click billing rather than a rate anyone set.
    """
    rows = _two_campaign_rows()

    assert _cell(rows, "cpm", 0, "total") == 50000.0
    assert _cell(rows, "ctr", 0, "total") == 10.0  # 14 clicks / 140 views


def test_total_ctr_carries_its_advertising_clicks_for_the_hover() -> None:
    """«Общая»'s «Клики» are the funnel's, so the CTR's own numerator rides beside it.

    The hover divides these 14 advertising clicks by the column's 140 показы —
    the funnel's clicks would give a CTR that never happened.
    """
    rows = _two_campaign_rows()

    assert _cell(rows, "ad_clicks", 0, "total") == 14.0
    assert _cell(rows, "ad_clicks", 0, "organic") is None
    assert _cell(rows, "ad_clicks", 0, "manual_search") is None


def test_total_cpm_is_blank_on_an_unadvertised_day() -> None:
    """No показы, no price per thousand of them — «—» rather than a zero."""
    funnel_rows = [_funnel_row(DAY1, open_count=200, cart_count=20, order_count=10)]

    rows = _matrix(campaigns={}, ad_rows=[], funnel_rows=funnel_rows)

    assert _cell(rows, "cpm", 0, "total") is None


def test_catalog_column_stays_empty() -> None:
    """The legacy «Каталог» zone no longer exists in the v2 API."""
    rows = _two_campaign_rows()
    for key in rows:
        assert _cell(rows, key, 0, "uni_catalog") is None


def test_buyout_percent_uses_lagged_window() -> None:
    """«Процент выкупа» for day D aggregates the cohorts of [D-21, D-7].

    The matured cohort in the window has 4 buyouts and 6 refusals -> 40% of its
    10 decided deliveries. DAY1's own cohort is OUTSIDE its lagged window (too
    recent) and must not contribute.
    """
    rows = _two_campaign_rows()

    assert _cell(rows, "buyout_percent", 0, "total") == 40.0
    assert _cell(rows, "buyout_percent", 1, "total") == 40.0
    assert _cell(rows, "buyout_percent", 0, "manual_search") is None


def test_buyout_percent_counts_refusals_of_zero_buyout_cohorts() -> None:
    """A cohort with zero buyouts still contributes its refusals.

    Regression: the metric used to reconstruct the denominator from WB's own
    whole-number cohort percent (``buyout_count / buyoutPercent``). A cohort
    that bought out nothing reports ``buyoutPercent = 0``, so it was skipped
    entirely and its refusals never reached the denominator — which printed 41%
    for SKU 914394276 where WB said 16%.

    Here: 2 buyouts + 2 refusals, plus a cohort of 6 pure refusals -> 2 of 10
    decided deliveries = 20%. Skipping the zero-buyout cohort would give 50%.
    """
    funnel_rows = [
        _funnel_row(DAY1, order_count=10, buyout_count=5),
        _funnel_row(DAY1 - timedelta(days=10), order_count=4, buyout_count=2, cancel_count=2),
        _funnel_row(DAY1 - timedelta(days=11), order_count=7, buyout_count=0, cancel_count=6),
    ]

    rows = _matrix(campaigns={}, ad_rows=[], funnel_rows=funnel_rows)

    assert _cell(rows, "buyout_percent", 0, "total") == 20.0


def test_buyout_percent_is_blank_until_the_cohort_pass_refreshes() -> None:
    """An unrefreshed cohort (``cancel_count`` NULL) is excluded, not read as 0.

    Treating NULL as "no refusals" would invent a 100% cohort out of a day the
    aggregate has simply never been asked about.
    """
    funnel_rows = [
        _funnel_row(DAY1, order_count=10, buyout_count=5),
        _funnel_row(DAY1 - timedelta(days=10), order_count=4, buyout_count=2, cancel_count=None),
    ]

    rows = _matrix(campaigns={}, ad_rows=[], funnel_rows=funnel_rows)

    assert _cell(rows, "buyout_percent", 0, "total") is None


def test_day_without_any_data_renders_empty() -> None:
    """A day with no funnel and no ads yields None across ad/total/organic."""
    rows = _two_campaign_rows()

    for bucket in ("uni_search", "manual_search", "uni_shelves", "total", "organic"):
        assert _cell(rows, "views", 1, bucket) is None
        assert _cell(rows, "clicks", 1, bucket) is None
