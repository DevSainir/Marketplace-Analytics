"""The pages the post-deploy smoke probe opens, one module per page.

``scripts/smoke_after_deploy.py`` is the entrypoint the deploy runs and says
why the probe exists; this package is what it opens. Split by page because
each page is built the way its own module's ``deps/`` builds it, and that
wiring is most of the code:

* :mod:`~scripts.smoke.monitoring` — the SKU list and the busiest cards.
* :mod:`~scripts.smoke.finreports` — P&L: the periods, the week's report, the balance.
* :mod:`~scripts.smoke.heatmap` — the grid and its catalogue.
* :mod:`~scripts.smoke.ab_tests` — the list and the newest test.
* :mod:`~scripts.smoke.report` — the outcome, and how one page is opened.
* :mod:`~scripts.smoke.probe` — all of them, in order.
"""

from scripts.smoke.monitoring import busiest_cards
from scripts.smoke.probe import smoke
from scripts.smoke.report import PageSkipped, SmokeReport

__all__ = ["PageSkipped", "SmokeReport", "busiest_cards", "smoke"]
