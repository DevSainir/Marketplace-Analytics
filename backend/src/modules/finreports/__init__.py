"""Financial-reports module (``finreports``).

Harvests the WildBerries weekly realization (settlement) report and its daily
provisional tail, and turns them — together with the seller's own cost prices —
into a settlement-basis profit-and-loss statement, per-SKU reports and the
stock balance by warehouse.

See ``docs/finreports/PNL.md`` for how the statement is derived from WB's rows
and ``docs/finreports/MIGRATION_TO_FINANCE_V1.md`` for the finance-api cutover.
"""
