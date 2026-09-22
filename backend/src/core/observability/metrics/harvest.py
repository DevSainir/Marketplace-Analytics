"""Harvest and backfill metrics — the business outcome, not the transport.

Both families exist because a task-level success metric cannot see the failures
this service actually produces: a harvest that ran and wrote nothing, and a
backfill lane that stopped without raising.
"""

from __future__ import annotations

from typing import Final

from prometheus_client import Counter, Gauge, Histogram

# --------------------------------------------------------------------------- #
# Harvest — the business outcome, not the transport.
# --------------------------------------------------------------------------- #

#: How long one harvest took, by kind and outcome. Separate from
#: `celery_task_duration_seconds` because a harvest is not a task: one task
#: harvests many workspaces, and a partial harvest (some sources failed, the
#: task succeeded) is the outcome this service produces most often and the one
#: a task-level metric cannot express.
HARVEST_DURATION: Final[Histogram] = Histogram(
    "harvest_duration_seconds",
    "Duration of one harvest run, by kind and outcome.",
    ["harvest", "outcome"],
    buckets=(1.0, 5.0, 15.0, 30.0, 60.0, 180.0, 600.0, 1800.0, 3600.0),
)

#: Rows actually written, by harvest and source. The metric that distinguishes
#: "the harvest succeeded" from "the harvest did anything" — and this codebase
#: has already shipped the gap between those two: after the Redis pool leak,
#: every run reported success with `funnel_rows: 0` for days
#: (see `src.core.tasks.run_task`). A counter that flatlines while its task
#: keeps succeeding is exactly that failure, made alertable.
HARVEST_ROWS: Final[Counter] = Counter(
    "harvest_rows_processed_total",
    "Rows ingested by a harvest, by kind and source.",
    ["harvest", "source"],
)

#: Harvests that finished with at least one source missing. A tolerated
#: partial is a design decision (a failed source must not lose the rest of the
#: run), which is precisely why it needs a counter: without one, the tolerance
#: is indistinguishable from the absence of a problem.
HARVEST_PARTIAL: Final[Counter] = Counter(
    "harvest_partial_total",
    "Harvests that completed with one or more sources unavailable.",
    ["harvest", "source"],
)

# --------------------------------------------------------------------------- #
# History backfill — the one job whose failure is silent by construction.
# --------------------------------------------------------------------------- #

#: Backfill lanes that claim to be running and have stopped moving, fleet-wide.
#:
#: This is the metric the 2026-09-10 incident had no equivalent of. A new org's
#: history arrives as four lanes of self-enqueueing ticks, and a tick that dies
#: before its re-enqueue ends the whole walk with NOTHING scheduled to notice:
#: no exception reaches a caller, no counter of work-done moves, and the lane
#: simply stays at whatever it had reached. NEVA's P&L lane died on its first
#: tick and sat there for eleven hours; the only reason anyone found out is that
#: a person happened to look.
#:
#: A counter of what the backfill DID could not have shown that — the failure is
#: the absence of work, not the presence of a bad result. Only a gauge of "how
#: many lanes are stuck right now" makes silence visible.
#:
#: Deliberately NOT labelled by workspace: `/metrics` has no tenancy check
#: because it has no tenant. "Whose backfill" is a question for the logs, which
#: carry `workspace_id` on every line. This answers "is anybody stuck".
#:
#: `livemostrecent`: one sweep computes this for the whole fleet every fifteen
#: minutes, so the newest computation is the truth. Summing across prefork
#: children would multiply it by however many ran the sweep.
BACKFILL_LANES_STALLED: Final[Gauge] = Gauge(
    "backfill_lanes_stalled",
    "Backfill lanes that are running but have not progressed, across all workspaces.",
    multiprocess_mode="livemostrecent",
)

#: Lanes the watchdog has restarted. Labelled by lane — four bounded values, no
#: caller-chosen string ever reaches it.
#:
#: Read WITH the gauge above, because the pair answers the question an alert
#: actually needs: a lane stalling and being restarted is the system healing
#: itself, while a lane stalling and being restarted repeatedly without the
#: gauge falling is the restart not working — which is a different incident and
#: the one worth waking somebody for.
BACKFILL_LANE_RESTARTS: Final[Counter] = Counter(
    "backfill_lane_restarts_total",
    "Backfill lanes restarted by the stalled-lane watchdog, by lane.",
    ["lane"],
)

#: Lane ticks that raised instead of recording a step. Distinct from a stall:
#: this is the moment of death, the gauge is the consequence of it, and having
#: both is what lets an alert say whether the lane is failing repeatedly or
#: failed once and was never picked up.
BACKFILL_LANE_FAILURES: Final[Counter] = Counter(
    "backfill_lane_failures_total",
    "Backfill lane ticks that ended in an exception, by lane.",
    ["lane"],
)

#: Settlement days inside the harvested history that no report period covers —
#: summed over every workspace, because a metric may not name a tenant.
#:
#: This is the half the 31.08 incident was missing. The harvest already had
#: rows-per-source and failed-source counters, and neither moved: the walk
#: succeeded, wrote what it was asked for, and simply stopped asking about a day
#: WB had not served yet. A gap is invisible to every counter that measures what
#: a run DID; it is only visible in what the history does not contain.
#:
#: Fleet-wide by construction — `/metrics` has no tenancy check because it has
#: no tenant. "Which seller" is a question for the logs, which carry
#: `workspace_id` on every line; this answers "is anyone short a day".
#:
#: `livemostrecent`: one nightly pass computes this for the whole fleet, so the
#: newest computation is simply the truth. Summing across prefork children would
#: multiply it by however many happened to have run it, and `livemax` would
#: strand a stale count after the gap was repaired.
SETTLEMENT_GAP_DAYS: Final[Gauge] = Gauge(
    "finreports_settlement_gap_days",
    "Settlement days covered by no harvested report, summed over all workspaces.",
    multiprocess_mode="livemostrecent",
)


#: Bucket edges, in hours, for how far apart sellers receive the same report.
#:
#: Fine at the bottom because the interesting question is «is it zero», and
#: coarse at the top because anything past a day is «staggered» whatever the
#: exact figure.
_SPREAD_BUCKETS: Final[tuple[float, ...]] = (0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 24.0, 48.0)

#: Hours between the FIRST seller to receive a settlement period and this one.
#:
#: The measurement that decides whether shared discovery is worth building. On
#: the report day every seller currently spends its own requests asking WB the
#: same question — «are you serving today's report» — and one answer could
#: serve the fleet. That is only true if WB publishes to everyone at once, and
#: nothing we hold says whether it does.
#:
#: Read it as an UPPER BOUND on WB's own spread, never as a measurement of it:
#: the figure includes our probe cadence, our rate budget and anything that
#: delayed one seller's tick. So a distribution piled into the bottom bucket is
#: conclusive — WB published simultaneously and we saw it — while a wide one is
#: ambiguous and needs the logs, which name the seller, to interpret.
#:
#: Fleet-wide and unlabelled by tenant, like everything on `/metrics`.
SETTLEMENT_PUBLICATION_SPREAD: Final[Histogram] = Histogram(
    "settlement_publication_spread_hours",
    "Hours between the first seller receiving a settlement period and this one.",
    buckets=_SPREAD_BUCKETS,
)


#: How far our payout for a report is from WB's own figure, per report.
#:
#: `sales-reports/list` carries WB's `forPaySum`, so since 2026-09-22 the P&L
#: can be checked against something rather than only against itself —
#: `docs/finreports/PNL.md` warns that most ways to get a settlement figure
#: wrong produce a plausible statement, not an error.
#:
#: Buckets start below a kopeck so agreement is distinguishable from
#: near-agreement, and end high enough that a whole operation class going
#: unsigned is one bucket rather than `+Inf`. Absolute, because the direction
#: of the error says nothing the magnitude does not.
SETTLEMENT_PAYOUT_DIVERGENCE: Final[Histogram] = Histogram(
    "settlement_payout_divergence",
    "Absolute gap between WB's own forPaySum for a report and ours.",
    buckets=(0.005, 1.0, 10.0, 100.0, 1_000.0, 10_000.0, 100_000.0),
)
