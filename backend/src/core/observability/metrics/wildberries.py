"""WildBerries call, latency and rate-budget metrics.

The dependency that fails most and least visibly: an over-budget analytics
request is answered with a held-open connection rather than a 429, so the
outcomes counted here include the two that have no HTTP status of their own.
"""

from __future__ import annotations

from typing import Final

from prometheus_client import Counter, Gauge, Histogram

# --------------------------------------------------------------------------- #
# WildBerries — the dependency that fails most, and least visibly.
# --------------------------------------------------------------------------- #

#: Every WB call, by surface, endpoint and outcome.
#:
#: `status` carries the HTTP code as a string, or one of the two non-HTTP
#: outcomes: `transport_error` (the connection failed or timed out) and
#: `rate_blocked` (our own gate refused to send, because WB's stated wait
#: exceeded the queue cap). Those two are counted here rather than dropped
#: because they are how WB actually fails — an over-budget analytics request
#: is answered with a held-open connection, not a 429 (measured 2026-07-30),
#: and a failure that produces no status would otherwise be invisible in the
#: one metric that is supposed to show WB's health.
WB_API_REQUESTS: Final[Counter] = Counter(
    "wb_api_requests_total",
    "WildBerries API requests by surface, endpoint and outcome.",
    ["surface", "endpoint", "status"],
)

#: How long WB took to answer, per attempt. Buckets stretch to 120s on
#: purpose: the interesting part of this distribution is the tail, where a
#: request sits behind an empty bucket until a read timeout fires, and default
#: buckets (top out at 10s) would put every one of those in `+Inf` and show
#: nothing.
WB_API_DURATION: Final[Histogram] = Histogram(
    "wb_api_request_duration_seconds",
    "Round-trip time of one WildBerries API attempt.",
    ["surface", "endpoint"],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 20.0, 30.0, 60.0, 120.0),
)

#: What WB last said was left in this endpoint's bucket
#: (`x-ratelimit-remaining`). A last-observation for humans to read on a
#: dashboard, and **not something to alert on** — the second paragraph is the
#: correction to a claim this comment used to make.
#:
#: `livemostrecent` because the truthful answer is "what the most recent
#: observation from a process that is still alive said" — summing across
#: workers would invent budget WB never granted, and `max` would report the
#: luckiest worker's view right up to the moment everything stalls.
#:
#: It was described here as the leading indicator for the whole harvest, on the
#: reasoning that it reaches zero before anything fails. The first half is true
#: and the conclusion does not follow. The gauge is written only where it is
#: set — inside `RateGate.observe`, i.e. only when a WB response arrives — and
#: nothing decays it. WB's bucket refills on a timer; this value does not. The
#: last request of any burst therefore reports `remaining: 0` legitimately, and
#: that zero persists until the next harvest happens to touch the same
#: endpoint, which on a rarely-called one is hours. Measured on prod
#: 2026-09-07: `/adv/v3/fullstats` sat at 0 for over 24 hours while all 14 of
#: its requests returned 200. `livemostrecent` compounds it for alerting: when
#: a prefork child is recycled its file is removed, so the series stops
#: existing and any alert on it RESOLVES, then fires again from the next child.
#: `WbRateBudgetExhausted` and `WbRatePacingPressure` are built on counters for
#: exactly these reasons; see the note above them in `alerts.yml`.
WB_RATE_LIMIT_REMAINING: Final[Gauge] = Gauge(
    "wb_rate_limit_quota_remaining",
    "Tokens WB reported remaining in this endpoint's bucket.",
    ["surface", "endpoint"],
    multiprocess_mode="livemostrecent",
)

#: Seconds spent waiting for a rate token before sending. Rising pacing
#: pressure is what a harvest that is about to overrun its window looks like an
#: hour before it does.
WB_RATE_LIMIT_WAIT: Final[Counter] = Counter(
    "wb_rate_limit_wait_seconds_total",
    "Cumulative seconds spent waiting on the client-side WB rate gate.",
    ["surface", "endpoint"],
)

#: Bucket edges for a penalty block WB demanded, in seconds.
#:
#: The span is deliberately enormous — a minute to a week — because that is the
#: span the measurements cover. On 2026-09-17 the settlement endpoint escalated
#: 28 197 -> 18 624 -> 302 940 s against one workspace, and the last of those is
#: four and a half days. Buckets that stopped at an hour would have recorded
#: all three as «+Inf» and said nothing about the escalation, which is the only
#: thing worth seeing here.
_BLOCK_BUCKETS: Final[tuple[float, ...]] = (
    60.0,
    300.0,
    900.0,
    1_800.0,
    3_600.0,
    10_800.0,
    32_400.0,
    86_400.0,
    259_200.0,
    604_800.0,
)

#: How long WB shut an endpoint for, per penalty block, as WB itself stated it.
#:
#: A histogram rather than a gauge, and the distinction is the reason this
#: exists. `WB_RATE_LIMIT_REMAINING` above is a gauge nothing decays, so it
#: cannot be alerted on — its own comment says so. A block is an EVENT: it
#: happens at an instant, it has a magnitude, and what matters is the magnitude
#: growing across events. `increase(..._count[6h])` says how often we are being
#: refused and the bucket distribution says how hard, so an escalation from
#: nine hours to a hundred and five is visible while it is happening rather
#: than excavated from logs two days later, which is what it cost the first
#: time (prod, 2026-09-17).
#:
#: Recorded with the wait WB DEMANDED, not the longer one we then serve — the
#: margin in `penalise` is our policy and would make the series describe us
#: rather than WB.
WB_RATE_LIMIT_BLOCK: Final[Histogram] = Histogram(
    "wb_rate_limit_block_seconds",
    "Length of a penalty block WB demanded, per block.",
    ["surface", "endpoint"],
    buckets=_BLOCK_BUCKETS,
)
