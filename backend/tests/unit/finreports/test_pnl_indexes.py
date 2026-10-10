"""The partial indexes the per-article P&L depends on, against what it queries.

A partial index is only used when its predicate covers the query's filter, and
nothing about that connection is visible in either file: rename the operation in
:data:`SALE_OPERS` and the query still returns the right answer, just by reading
the whole table again. On the largest кабинет that is the difference between
0.3 s and 4 s, and it would show up as «P&L got slow again» months later.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from src.modules.finreports.constants import LOGISTICS_OPER, SALE_OPERS

pytestmark = pytest.mark.unit

VERSIONS = pathlib.Path(__file__).resolve().parents[3] / "alembic" / "versions"
MIGRATION = VERSIONS / "b3d7f18c05ae_pnl_partial_indexes.py"


def test_the_sale_index_covers_every_operation_the_report_counts() -> None:
    """The index predicate names exactly the operations ``SALE_OPERS`` holds."""
    predicate = re.search(r"WHERE supplier_oper_name IN \(([^)]+)\)", MIGRATION.read_text())
    assert predicate is not None
    indexed = {value.strip().strip("'") for value in predicate.group(1).split(",")}

    assert indexed == set(SALE_OPERS)


    assert predicate is not None

    assert predicate.group(1) == LOGISTICS_OPER
