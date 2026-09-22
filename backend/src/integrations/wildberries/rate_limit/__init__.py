"""Client-side pacing for WB's per-endpoint token buckets.

Split by responsibility once the mechanism and its configuration stopped fitting
in one file: :mod:`gates` holds the bucket, the protocol and the Redis-down
fallback; :mod:`surfaces` holds the per-family sizes and the factories every
client calls. The names below are the public API and have not moved — an
importer of this package sees exactly what it saw when this was one module.
"""

from __future__ import annotations

from src.integrations.wildberries.rate_limit.gates import (
    NullRateGate,
    RateGate,
    TokenBucketRateGate,
)
from src.integrations.wildberries.rate_limit.surfaces import (
    ADVERTISING_ENDPOINT_BUCKETS,
    ANALYTICS_ENDPOINT_BUCKETS,
    FINANCE_REPORT_ENDPOINT_BUCKETS,
    STATISTICS_ENDPOINT_BUCKETS,
    advertising_rate_gate,
    analytics_rate_gate,
    catalogue_rate_gate,
    finance_reports_rate_gate,
    marketplace_rate_gate,
    settlement_walk_rate_gate,
    statistics_rate_gate,
)

__all__ = [
    "ADVERTISING_ENDPOINT_BUCKETS",
    "ANALYTICS_ENDPOINT_BUCKETS",
    "FINANCE_REPORT_ENDPOINT_BUCKETS",
    "STATISTICS_ENDPOINT_BUCKETS",
    "NullRateGate",
    "RateGate",
    "TokenBucketRateGate",
    "advertising_rate_gate",
    "analytics_rate_gate",
    "catalogue_rate_gate",
    "finance_reports_rate_gate",
    "marketplace_rate_gate",
    "settlement_walk_rate_gate",
    "statistics_rate_gate",
]
