"""The Finance surface's realization report — the endpoint WB still maintains.

`reportDetailByPeriod` was announced for shutdown on 15.07.2026 and is gone
from WB's documentation. These pin the replacement's two hazards, both of
which would be silent:

* **The twenty renames are not a camelCase rule.** Some `ppvz_` prefixes
  survived and some were dropped, so a converter would leave the money columns
  null — a plausible P&L rather than an error.
* **The detail method carries the report id IN the path**, and WB meters it
  per method. Keyed on the raw path, every report would get its own empty
  bucket and nothing would be paced at all.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from src.core.config import settings
from src.integrations.wildberries.clients import ReportPeriod, WBFinanceReportsClient
from src.integrations.wildberries.endpoints import (
    SALES_REPORTS_DETAILED_PATH,
    endpoint_label,
    sales_report_detail_path,
)
from src.integrations.wildberries.rate_limit import FINANCE_REPORT_ENDPOINT_BUCKETS
from src.integrations.wildberries.schemas import WBFinanceReportHeader, WBFinanceReportRow
from tests.support import wb_labels as wb

pytestmark = pytest.mark.unit

#: A synthetic settlement row in the exact shape the Finance surface serves: the
#: same keys and JSON types (money as strings, counts and ids as numbers), trimmed
#: to the fields the mapping reads. The values are invented.
SAMPLE_ROW: dict[str, Any] = {
    "reportId": 900000202,
    "dateFrom": "2026-08-17",
    "dateTo": "2026-08-23",
    "createDate": "2026-08-24",
    "currency": "KGS",
    "rrdId": 4100000000123,
    "giId": 30000001,
    "dlvPrc": 1.15,
    "subjectName": "Jeans",
    "nmId": 900000104,
    "brandName": "NORTH LINE",
    "vendorCode": "m-jnx01-blk",
    "title": "Straight jeans demo",
    "techSize": "52",
    "sku": "2000000000107",
    "quantity": 0,
    "retailPrice": "0",
    "retailAmount": "0",
    "officeName": "WB warehouse",
    "sellerOperName": wb.LOGISTICS,
    "rrDate": "2026-08-17",
    "shkId": 30000000042,
    "retailPriceWithDisc": "0",
    "deliveryAmount": 1,
    "returnAmount": 0,
    "deliveryService": "72.40",
    "giBoxTypeName": "Mix",
    "spp": 0,
    "kvwBase": 0,
    "kvw": 0,
    "forPay": "164.25",
    "vw": "11.80",
    "vwNds": "2.36",
    "paidStorage": "1.25",
    "paidAcceptance": "0",
    "sellerPromo": "0",
    "country": "Kyrgyzstan",
    "warehouseLogisticsCoeff": 1.15,
}


def test_every_renamed_field_lands_where_the_mapping_reads_it() -> None:
    """The twenty renames, asserted one by one against a payload in the wire shape.

    Stated exhaustively on purpose. A rule cannot express this set — `forPay`
    and `vw` lost the `ppvz_` prefix while `ppvzReward` kept it — so the only
    thing that can catch a wrong entry is naming the pair.
    """
    row = WBFinanceReportRow.model_validate(SAMPLE_ROW)

    assert row.realizationreport_id == 900000202  # reportId
    assert row.create_dt == date(2026, 8, 24)  # createDate
    assert row.rr_dt == date(2026, 8, 17)  # rrDate
    assert row.sa_name == "m-jnx01-blk"  # vendorCode
    assert row.ts_name == "52"  # techSize
    assert row.barcode == "2000000000107"  # sku
    assert row.currency_name == "KGS"  # currency
    assert row.site_country == "Kyrgyzstan"  # country
    assert row.supplier_oper_name == wb.LOGISTICS  # sellerOperName
    assert row.supplier_promo == Decimal(0)  # sellerPromo
    assert row.retail_price_withdisc_rub == Decimal(0)  # retailPriceWithDisc
    assert row.delivery_rub == Decimal("72.40")  # deliveryService
    assert row.storage_fee == Decimal("1.25")  # paidStorage
    assert row.acceptance == Decimal(0)  # paidAcceptance
    assert row.ppvz_for_pay == Decimal("164.25")  # forPay
    assert row.ppvz_vw == Decimal("11.80")  # vw
    assert row.ppvz_vw_nds == Decimal("2.36")  # vwNds
    assert row.ppvz_spp_prc == Decimal(0)  # spp
    assert row.ppvz_kvw_prc_base == Decimal(0)  # kvwBase
    assert row.ppvz_kvw_prc == Decimal(0)  # kvw


def test_money_arrives_as_a_string_and_stays_exact() -> None:
    """The new surface sends money as a string, and that is an improvement.

    A JSON float had to be trusted; `"72.40"` parses to a `Decimal` that is
    exactly 72.40. The assertion is that no float ever stands between the two
    — `Decimal(72.40)` is not `Decimal("72.40")`, and on a settlement report
    the difference accumulates into somebody's payout.
    """
    row = WBFinanceReportRow.model_validate(SAMPLE_ROW)

    assert row.delivery_rub == Decimal("72.40")
    assert row.delivery_rub != Decimal(72.40)  # noqa: RUF032 — that IS the point


def test_the_camel_case_default_still_covers_the_unrenamed_fields() -> None:
    """Forty-five fields only changed spelling, and must not need an entry."""
    row = WBFinanceReportRow.model_validate(SAMPLE_ROW)

    assert row.subject_name == "Jeans"
    assert row.brand_name == "NORTH LINE"
    assert row.gi_box_type_name == "Mix"
    assert row.delivery_amount == 1
    assert row.shk_id == 30000000042


def test_the_new_fields_worth_having_are_kept() -> None:
    """`title` is the product name the P&L joins content cards for today, and
    `warehouseLogisticsCoeff` the warehouse's logistics coefficient."""
    row = WBFinanceReportRow.model_validate(SAMPLE_ROW)

    assert row.title == "Straight jeans demo"
    assert row.warehouse_logistics_coeff == Decimal("1.15")


def test_a_report_header_carries_wbs_own_totals() -> None:
    """The oracle the P&L has never had.

    `PNL.md` warns that most ways to get a settlement figure wrong produce a
    plausible statement rather than an error. The header carries WB's own answer
    for the same report (invented sums here, in the shape WB serves them).
    """
    header = WBFinanceReportHeader.model_validate(
        {
            "reportId": 900000203,
            "dateFrom": "2026-08-24",
            "dateTo": "2026-08-25",
            "createDate": "2026-08-26",
            "currency": "KGS",
            "reportType": 1,
            "retailAmountSum": "512000.00",
            "forPaySum": "409600.00",
            "deliveryServiceSum": "96000.00",
            "paidStorageSum": "1800.00",
            "deductionSum": "45000.00",
            "penaltySum": "650.00",
        }
    )

    assert header.report_id == 900000203
    assert header.create_date == date(2026, 8, 26)
    assert header.for_pay_sum == Decimal("409600.00")
    assert header.date_to == date(2026, 8, 25)


def test_every_report_id_shares_one_rate_bucket() -> None:
    """WB meters the detail method, not the report.

    The id travels in the PATH, so a bucket keyed on the path as sent would be
    fresh for every report — three reports fetched back to back would leave in
    one second against a one-per-minute limit. The client pins the templated
    path as its rate key, and this is the assertion that the template and the
    real path actually collapse onto each other.
    """
    assert endpoint_label(sales_report_detail_path(900000202)) == SALES_REPORTS_DETAILED_PATH
    assert endpoint_label(sales_report_detail_path(1)) == SALES_REPORTS_DETAILED_PATH
    assert FINANCE_REPORT_ENDPOINT_BUCKETS[SALES_REPORTS_DETAILED_PATH] == (1, 60.0)


async def test_the_daily_lane_asks_for_the_daily_period_and_the_weekly_one_does_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`period` defaults to weekly at WB, and the request says so by omission.

    The parameter is the whole reason a daily settlement report existed unread:
    asked for a single day WITHOUT it, WB answers 204 — indistinguishable from
    «the report is not formed yet». So the daily lane must send it, and the
    settled lane must keep sending the request it has always sent: `weekly` is
    documented as the default, `daily` is measured, and an explicitly weekly
    request against a fleet of sellers is neither.
    """
    sent: list[dict[str, Any]] = []

    async def _capture(
        self: Any, method: str, path: str, *, json_body: dict[str, Any], **_: Any
    ) -> list[Any]:
        sent.append(json_body)
        return []

    monkeypatch.setattr(WBFinanceReportsClient, "_request", _capture)
    client = WBFinanceReportsClient(settings, token="a-finance-token")

    await client.list_reports(date_from=date(2026, 9, 14), date_to=date(2026, 9, 20))
    await client.list_reports(
        date_from=date(2026, 9, 21), date_to=date(2026, 9, 22), period=ReportPeriod.DAILY
    )

    assert "period" not in sent[0]
    assert sent[1]["period"] == "daily"
