"""Shared bounds for the ``monitoring`` module.

Neutral values imported by both the schema and service layers, so neither has to
depend on the other to agree on the same number. Mirrors
``finreports/constants.py``.
"""

from __future__ import annotations

#: Hard ceiling on a requested analysis window, in days. Bounds the work any
#: single request can demand — an unbounded ``date_from=2000-01-01`` was a
#: memory/latency DoS. ``resolve_window`` rejects a wider window, and the
#: request schemas reject a body claiming more days than one could contain.
MAX_WINDOW_DAYS: int = 366

#: Most day columns a matrix working copy may carry: the widest window, made
#: inclusive of both endpoints.
#:
#: The preview/save endpoints take the whole working copy *from the client* and
#: recompute every cell, so without this a body claiming a million days is a
#: million days of server-side arithmetic — the window ceiling above bounds the
#: days we SELECT, and bounded nothing about the days a caller can assert.
MAX_MATRIX_DAYS: int = MAX_WINDOW_DAYS + 1

#: Most SKUs one request may name. Comfortably above the largest real catalogue
#: on the platform, and short of a query whose ``IN`` list is its own denial of
#: service. Applies to every list of ``nm_ids`` a caller supplies.
MAX_NM_IDS_PER_REQUEST: int = 10_000

__all__ = [
    "MAX_MATRIX_DAYS",
    "MAX_NM_IDS_PER_REQUEST",
    "MAX_WINDOW_DAYS",
]
