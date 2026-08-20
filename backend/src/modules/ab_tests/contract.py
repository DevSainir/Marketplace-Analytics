"""Public contract for the A/B-tests module.

Deliberately small: nothing else in the backend needs a test's internals, and
the module reads other modules' data (advertising days) rather than being read.
Exposed for the app wiring and for any future module that wants to know whether
a card is currently under test — a fact that changes how its metrics should be
read.
"""

from __future__ import annotations

from src.modules.ab_tests.models import AbTestStatus
from src.modules.ab_tests.routers import router
from src.modules.ab_tests.schemas import AbTestDetail, AbTestRead, VariantMetrics

__all__ = [
    "AbTestDetail",
    "AbTestRead",
    "AbTestStatus",
    "VariantMetrics",
    "router",
]
