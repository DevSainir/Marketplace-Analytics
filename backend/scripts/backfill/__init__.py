"""The deep-history backfill, split by harvest phase.

``backfill_history.py`` is the CLI and the orchestrator; this package holds the
phases it runs. Each module owns one WB surface end to end — its pagination,
its rate-limit quirks, and its own idea of what "already backfilled" means —
because those differ enough per surface that sharing one function would mean a
parameter for every difference.

* :mod:`~scripts.backfill.common` — the shared service graph and phase counters.
* :mod:`~scripts.backfill.sales` — the account-wide sale/return feed.
* :mod:`~scripts.backfill.funnel` — the funnel-aggregate walk (also reused by
  ``seed_workspace.py``, which needs the same walk over a shorter window).
* :mod:`~scripts.backfill.advertising` — campaign fullstats and search zones.
"""
