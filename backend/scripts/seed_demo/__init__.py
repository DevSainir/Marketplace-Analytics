"""The demo: a whole shop's worth of fabricated data, for `make demo`.

``python -m scripts.seed_demo`` empties a demo database and fills it with one
account, one company and one workspace holding a year of an invented
apparel seller's WildBerries life — card funnel, prices, stock, advertising,
weekly settlement reports, cost prices, heatmap groups and A/B photo tests. No
WB token is involved and nothing leaves the machine.

The pieces, each writing one area:

* :mod:`~scripts.seed_demo.catalogue` — the articles and campaigns;
* :mod:`~scripts.seed_demo.simulation` — the day-by-day figures every table
  shares, a pure function of the calendar date;
* :mod:`~scripts.seed_demo.monitoring`, :mod:`~scripts.seed_demo.advertising`,
  :mod:`~scripts.seed_demo.settlement`, :mod:`~scripts.seed_demo.ab_tests`,
  :mod:`~scripts.seed_demo.extras` — the writers;
* :mod:`~scripts.seed_demo.tenancy` — the account, and the guard that refuses
  any database holding more than the demo.
"""
