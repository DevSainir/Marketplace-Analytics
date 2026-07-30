"""Upsert column lists for the ``finreports`` ingestion.

Each list names the columns overwritten on conflict — everything the source
publishes except the conflict key itself. They live apart from the service
because they are data, not logic: the settlement list alone is ~50 entries, and
keeping it inline pushed :mod:`~src.modules.finreports.services.ingestion.service`
past the module's 500-line ceiling.

A column missing from :data:`TXN_UPDATE` is a column that silently keeps its
*old* value when a report is re-harvested — which is exactly how a restated week
would go unnoticed. Add here whenever a column is added to the model.
"""

from __future__ import annotations

#: ``logistics_transaction`` — everything but ``rrd_id``.
TXN_UPDATE = [
    "report_id",
    "workspace_id",
    "nm_id",
    "barcode",
    "sa_name",
    "ts_name",
    "srid",
    "shk_id",
    "gi_id",
    "office_name",
    "subject_name",
    "brand_name",
    "rr_dt",
    "order_dt",
    "sale_dt",
    "supplier_oper_name",
    "doc_type_name",
    "bonus_type_name",
    "gi_box_type_name",
    "delivery_method",
    "currency_name",
    "site_country",
    "srv_dbs",
    "quantity",
    "delivery_amount",
    "return_amount",
    "retail_price",
    "retail_amount",
    "retail_price_withdisc_rub",
    "sale_percent",
    "commission_percent",
    "ppvz_for_pay",
    "ppvz_vw",
    "ppvz_vw_nds",
    "ppvz_sales_commission",
    "ppvz_reward",
    "ppvz_spp_prc",
    "ppvz_kvw_prc_base",
    "ppvz_kvw_prc",
    "acquiring_fee",
    "acquiring_percent",
    "acquiring_bank",
    "payment_processing",
    "product_discount_for_report",
    "supplier_promo",
    "seller_promo_discount",
    "loyalty_discount",
    "installment_cofinancing_amount",
    "cashback_amount",
    "cashback_discount",
    "cashback_commission_change",
    "agency_vat",
    "dlv_prc",
    "delivery_rub",
    "penalty",
    "additional_payment",
    "rebill_logistic_cost",
    "storage_fee",
    "acceptance",
    "deduction",
    "fix_tariff_date_from",
    "fix_tariff_date_to",
]

#: ``financial_report`` — everything but ``report_id``.
REPORT_UPDATE = ["workspace_id", "date_from", "date_to", "currency", "create_dt"]

    "box_delivery_base",
    "box_delivery_liter",
    "box_delivery_coef_pct",
    "box_storage_base",
    "box_storage_liter",
    "box_storage_coef_pct",
    "geo_name",
    "dt_till_max",
]

BASELINE_UPDATE = [
    "vendor_code",
    "length_cm",
    "width_cm",
    "height_cm",
    "weight_brutto_kg",
    "volume_l",
    "workspace_id",
    "document_proof_id",
]

BILLED_UPDATE = [
    "nm_id",
    "barcode",
    "volume_l",
    "warehouse_coef",
    "calc_type",
    "warehouse_price",
]

PENALTY_UPDATE = [
    "subject_name",
    "prc_over",
    "length_sup",
    "width_sup",
    "height_sup",
    "volume_sup",
    "length",
    "width",
    "height",
    "volume",
    "penalty_amount",
    "reversal_amount",
    "photo_url",
    "is_valid",
    "is_valid_dt",
    "workspace_id",
]

MEASUREMENT_UPDATE = [
    "subject_name",
    "length_cm",
    "width_cm",
    "height_cm",
    "volume_l",
    "measured_at",
    "photo_url",
    "workspace_id",
]

__all__ = [
    "BASELINE_UPDATE",
    "BILLED_UPDATE",
    "MEASUREMENT_UPDATE",
    "PENALTY_UPDATE",
    "REPORT_UPDATE",
    "TXN_UPDATE",
]
