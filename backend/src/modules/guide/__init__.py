"""Guide — the capture buffer for WB data nobody uses yet.

Every other module here earns its keep: the funnel drives the matrix, the
settlement rows drive the P&L, the advertising rows drive ДРР. This one earns
nothing today. It exists because WB deletes things.

Several WB feeds are served over a window that closes and never reopens — the
заявки на возврат live fourteen days, the лента заказов a hundred and eighty
eight, the tariff calendar seventy. A dataset we do not collect today is not a
dataset we can collect later; it is one we can never collect at all for those
dates. So `guide` collects them now, at the cheapest cadence that does not lose
anything, and stores WB's answer verbatim until somebody knows what to ask of
it.

Two rules follow from "earns nothing today", and both are load-bearing:

* **It must never cost the real harvests anything.** The WB rate buckets are
  keyed per endpoint, so these calls cannot drain the funnel's, the settlement
  walk's or fullstats' budgets — but the worker's four slots and the database
  are shared. Hence the off-peak schedule, one lock across all three cadences,
  a bounded number of windows per run, and a soft time limit well under the
  hour every other task may take.
* **It stores payloads, not a schema.** `guide_record` is `(source, workspace,
  key) -> jsonb`. Modelling these feeds properly now would mean guessing their
  shape twice: once here, and again when one of them graduates into the module
  that actually uses it. When that happens, the typed table belongs there and
  this one keeps the history the typed one cannot reach back for.

What is captured, at what cadence and why lives in :mod:`.sources`, which is
the file to read first and the only one to edit when adding a feed.
"""
