# Migrating the settlement report off the endpoint WB switched off

> **Done, 2026-09-22 — except phase 5, done 2026-09-23, and phase 7's last deletions,
> 2026-09-24.** Six phases landed in one sitting and every workspace harvested the latest
> weekly report the same day; on the old endpoint it would have waited until the penalty block
> lifted the next morning. The cutover was immediate — there never was a "behind a setting for
> one cycle" — and the phase sections below say what actually landed where it differs from the
> plan.
>
> **Phase 5 was not done and this banner said it was**, which is worth more than the day it
> cost. The forward harvest moved to report ids and the history backfill did not, so it kept
> walking date spans on `sales-reports/detailed` — the by-period form this very document lists
> as risk 5 — and kept every constant it had been given by an endpoint serving four requests an
> hour: a 15-minute re-enqueue, a 90-minute pace ceiling, a three-hour watchdog, a
> three-empty-answers rule for an ambiguity `list` had already removed. It was invisible
> because the lane only runs for a NEW workspace and none had signed up since. The first new
> seller would have found it. See the phase-5 section below for what it became.
>
> **A correction, recorded because the mistake is instructive.** This note first said
> `workspaces.workspace_backfill` "held no rows at all, fleet-wide" — read off a `diagnose.py`
> probe that came back empty. The table carries a tenancy policy, so that probe could only ever
> see the diagnostic workspace, which has no lane row; the inference "therefore nobody has one" needed the
> opposite assumption about the table and had no more evidence than the one that was made.
> Another workspace's lane row was there all along, seeded earlier with a pre-rewrite cursor. It was
> rejected cleanly the next day, which is what the tolerant parser is for — but the claim was
> false when it was written.
>
> What phase 2 actually found, kept because it is the evidence the cutover rests on: a full
> weekly report fetched through the new endpoint and diffed against what we hold — **the same
> row set on both sides, 61 of 63 columns identical to the value.** The two that differed
> (`ppvz_vw`, `ppvz_vw_nds`) are the stored column's scale; quantizing the served value to
> numeric(18,10) and numeric(14,2) reproduces what is on disk exactly. The payout identity held
> on every sale and return row, and all three guessed renames — `sellerPromo`, `sku`,
> `country` — matched on every row.
>
> Phase 6 paid for itself immediately. WB's `forPaySum` decomposes as «Продажа» − «Возврат» −
> «Коррекция продаж» + compensations, to the kopeck — and our `RETURN_OPERS` was «Возврат»
> alone, so «Коррекция продаж» was added where WB subtracts it: a small but real gap on that
> report. **Not fixed at the time**: one report is one data point, and
> `settlement_payout_divergence` was to accumulate the rest.
>
> **That last sentence was not true when it was written, and the disagreement is now resolved
> (2026-09-24).** `reconcile_against_wb` existed from 22.09 but nothing called it, so the
> metric accumulated nothing for two days. It now runs every time a report is booked
> (`tasks/settlement/reconcile.py`, called from `_book_report`) and alerts as
> `SettlementPayoutDisagreesWithWb` on a disagreement of one unit of currency or more. The gap
> itself was not about the operation at all: the sign of `ppvz_for_pay` comes from
> `doc_type_name` — «Возврат» subtracts, anything else adds (`REFUND_DOC_TYPE` in
> `finreports/constants.py`) — and that rule matches WB's `forPaySum` to the kopeck on every
> report of one workspace's history. A rule tried first the same day, "always subtract «Коррекция продаж»", was
> wrong and was replaced within hours. [`PNL.md`](PNL.md), "The payout's sign comes from the
> document type, not the operation", has the reasoning.
>
> Phase 3 also answered the question shared discovery was waiting on. The first fleet harvest
> recorded a publication spread of a fraction of an hour across the sellers — which is our
> own sequential loop, not WB. WB publishes to everyone at once, and with discovery now on its
> own bucket there is nothing left for a scout to save.

`GET /api/v5/supplier/reportDetailByPeriod` — until 2026-09-22 the P&L's only source — was
announced for shutdown on **15 July 2026** and is absent from WB's current documentation.
When this plan was written we were still calling it, and everything built around it (one
request per ~917 s, escalating multi-hour blocks, a derived publication calendar, a probe
cadence, a shared-block mechanism) existed to survive a deprecated endpoint. None of it is in
the code now except the shared-block mechanism, kept in the rate gate for an endpoint that
behaves that way again.

The replacement is three methods on the Finance surface. All three answer on the «Финансы»
token we already hold — verified live on one workspace, 2026-09-22.

| method | purpose | limit |
| --- | --- | --- |
| `POST /api/finance/v1/sales-reports/list` | report headers + WB's own per-report totals | 1/min, burst 1 |
| `POST /api/finance/v1/sales-reports/detailed/{reportId}` | detail rows for one report | 1/min, burst 1 |
| `POST /api/finance/v1/sales-reports/detailed` | detail rows by period | 1/min, burst 1 |

Host `https://finance-api.wildberries.ru`. **Fifteen times** the rate we lived under, on a
maintained endpoint, with a discovery method that costs nothing from the detail budget.

## What the migration is worth

* **Budget.** 1/min instead of 1/917 s. A full-history backfill goes from hours to minutes —
  e.g. 50 pages take ~13 hours at the old rate and 50 minutes at the new one.
* **Discovery stops being expensive.** `list` is a separate bucket, so "is there a new report"
  no longer competes with fetching one. Shared discovery — designed, costed, not built —
  becomes unnecessary.
* **`createDate` is served, not derived.** `services/publication.py` inferred it from a
  calendar built over the whole report history; the API now states it. Keep the arithmetic as
  a cross-check, drop it as the source of truth.
* **A reconciliation oracle we have never had.** `list` returns WB's own totals per report:
  `retailAmountSum`, `forPaySum`, `deliveryServiceSum`, `paidStorageSum`, `deductionSum`,
  `penaltySum`, `additionalPaymentSum`, `bankPaymentSum`. [`PNL.md`](PNL.md) warns that most
  ways to get a settlement figure wrong produce a plausible statement rather than an error.
  This is the first thing we can check the statement *against*.
* **Fields we currently go elsewhere for.** `title` (product name — today a content-card
  join).

## The field map

92 fields against our 65. Forty-five match once camelCase is undone; twenty are renames; the
rest are new.

**The renames are NOT derivable by a camelCase rule** — some `ppvz_` prefixes survived
(`ppvzReward`, `ppvzSalesCommission`) and some were dropped (`vw`, `forPay`). A regex
converter would silently produce nulls for the money columns. This has to be an explicit
table:

| ours (persisted column) | new field |
| --- | --- |
| `realizationreport_id` | `reportId` |
| `create_dt` | `createDate` |
| `rr_dt` | `rrDate` |
| `sa_name` | `vendorCode` |
| `ts_name` | `techSize` |
| `barcode` | `sku` |
| `currency_name` | `currency` |
| `site_country` | `country` |
| `supplier_oper_name` | `sellerOperName` |
| `supplier_promo` | `sellerPromo` |
| `retail_price_withdisc_rub` | `retailPriceWithDisc` |
| `delivery_rub` | `deliveryService` |
| `storage_fee` | `paidStorage` |
| `acceptance` | `paidAcceptance` |
| `ppvz_for_pay` | `forPay` |
| `ppvz_vw` | `vw` |
| `ppvz_vw_nds` | `vwNds` |
| `ppvz_spp_prc` | `spp` |
| `ppvz_kvw_prc_base` | `kvwBase` |
| `ppvz_kvw_prc` | `kvw` |

**Money is now a string** (e.g. `"1234.56"`), not a JSON number. That is an improvement, not a
hazard: Pydantic parses a string straight to an exact `Decimal`, where a float had to be
trusted. It does mean any code reading the raw payload — as opposed to the parsed model —
changes behaviour.

**Do not trust the JSON types from one row.** The sample row has `agencyVat: 0` as an int and
`dlvPrc` as a float; a non-zero `agencyVat` may well arrive as a string like the other money.
Types must be settled over a whole report, which phase 2 does.

## The shape of the change

The mapping into `logistics_transaction` is one flat function,
`ingestion/rows.py::settlement_row`, and every column name it writes stays the same. So the
translation belongs **at the edge**: a new schema whose Pydantic aliases produce the field
names the rest of the code already uses. `rows.py`, `columns.py`, the model, the
repositories and the P&L are then untouched.

## Phases

Each phase is independently landable and leaves `main` working.

### 1. Client and schema, behind nothing

* `WBFinanceReportsClient` on `finance-api.wildberries.ru`, «Финансы» token:
  `list_reports(date_from, date_to)` and `stream_detail(report_id, rrd_id, limit)`.
* `WBFinanceReportRow` — the existing `WBReportDetailRow` field names, with `alias=` for each
  of the 20 renames and `populate_by_name=True`. The internal shape does not change.
* `StreamingJSONMixin._stream_json_items` must learn POST: it calls
  `build_request(method, path, params=params)` with no body. One parameter.
* Rate gate: a `finance` surface, both paths at `(1, 60.0)`.

Nothing calls any of it yet. Landing this alone is safe.

### 2. Verification against what we already hold

The step that makes the cutover safe, and it is cheap at 1/min.

A `scripts/diagnose.py` probe that, for each report already in `financial_report`: fetches it
through the new endpoint, maps it through the new schema, and diffs it row by row against
`logistics_transaction` on every persisted column. Report any field where the two disagree,
and any field whose JSON type differs from the sample row.

Two invariants worth asserting rather than eyeballing:

* the payout identity — `forPay = retailAmount − vw − vwNds − acquiringFee − ppvzReward` —
  which is the same one `schemas/finance.py` pins today and proves the money columns are
  mapped to the right places;
* WB's own `forPaySum` from `list` against `SUM(ppvz_for_pay)` over the report we hold.

**Do not proceed until a full report matches exactly.** A wrong mapping here produces a
plausible P&L, not an error.

### 3. Discovery moves to `list`

* `check_freshness` asks `list` instead of `fetch_first_row`. It is a different bucket, so the
  probe stops competing with the walk.
* `missing_periods` compares against `createDate` as served rather than as derived.
  `services/publication.py` stays, demoted to a cross-check: if WB's `createDate` ever
  disagrees with `date_to + 1`, that is worth an alert, not a silent correction.
* The probe cadence (`is_probe_hour`) can relax considerably — at 1/min the cost of asking
  hourly is nothing. Keep some decay so a stuck period cannot spin.

**What landed differs (2026-09-23).** `services/publication.py` was not demoted but deleted,
with the probe cadence, and **no `createDate` vs `date_to + 1` cross-check exists** — the alert
this section asked for was never built. The calendar's one remaining question, "WB formed
nothing for a day inside our history", is answered in SQL by the gap survey, and a report
`list` names is fetched by the tick that names it. The forward harvest ticked every 15 minutes
07:00–18:45 MSK and hourly outside that window until 2026-09-26; since then it runs on the
hours a report can arrive and asks WB only about sellers still owed one.

### 4. The walk moves to report ids

* `walk_settlement_windows` splits a date span into ≤ 7-day windows because a week was the
  natural grain of one request. With `list` we know the exact report ids we are missing, so
  the walk becomes: for each missing `reportId`, page `detailed/{reportId}` by `rrdId` until
  empty.
* `settlement_windows` and its tests go away; so does the whole "which window did not
  complete" prefix logic, replaced by "which report ids are complete".
* `completed_through` becomes "every report id up to here is fully ingested", which is a
  stronger and simpler watermark than a date prefix.

### 5. Backfill — done 2026-09-23

`tasks/backfill/` paced itself from `SETTLEMENT_PACE_CEILING_SECONDS` (90 min), and the
watchdog's patience was sized from it. All of that collapsed, and rather more with it, once
the lane's unit became a `reportId` like the harvest's:

* `span.py` — the gap-finder that inferred holes from stored settlement days, with a
  fourteen-day tolerance — is gone, replaced by `discovery.py`: a set difference against
  `list`. So is `PNL_EMPTY_STOP`, whose whole subject was an ambiguity `list` removes.
* Two measurements on one workspace made the shape obvious. **One `list` request covers the whole
  history at any width** — a three-year and a decade-wide window returned the same complete
  set of reports — and **one report is one request**, since even the largest weekly report
  fits well inside a 100 000-row page. So a tick re-lists rather than caching a backlog, and
  full history is 1 + N requests.
  *Superseded the same week:* a contiguous run of owed reports is now fetched by PERIOD
  through `stream_rows_by_period` (`tasks/settlement/window.py`), many reports to a page, and
  only a scattered backlog goes report by report. Full history on that workspace became a handful of
  requests instead of one per report. The window books nothing until every page has landed; a
  window too long for one tick hands back its `rrdId` cursor and the next tick continues it.
* A tick now walks up to twelve reports, bounded by a ten-minute deadline inside a
  fifteen-minute soft limit. One per tick spent two thirds of the lane's throughput waiting
  between ticks rather than inside them.
  *The ten minutes were wrong (2026-09-24):* a page started at the deadline still queues for
  its token and then runs, so 600 + 240 + 217 overran the 900 s soft limit. The budget is now
  derived — `_TICK_WORK_BUDGET_SECONDS` in `backfill/batch.py`, 900 − 240 (queue) − 240
  (longest page) − 120 (preamble) = 300 s.
* The pace ceiling is 15 minutes and lives in the lane; the watchdog goes back to the
  fleet-wide 45 minutes and the per-lane patience table is deleted. `LANE_RESTART_DELAY` for
  the lane drops from 15.5 minutes to 90 seconds.
* `finance_reports_rate_gate` had inherited `wb_statistics_walk_queue_seconds` (1000 s, sized
  for a 960 s refill) and so could sleep past its own caller's soft limit. It is
  `FINANCE_QUEUE_SECONDS`, 120 s (raised to 240 s the same day: at 120 it equalled the
  background reserve and a reserving caller refused its own request) — and with that,
  `settlement_walk_rate_gate` and the setting itself had no callers left and are deleted,
  which is two items of phase 7's list.
* `PNL_FLOOR_DAYS = 90` is now `WB_REPORTS_EPOCH`: there is no depth limit, because at one
  request a minute history costs about 52 minutes per year of weekly reports and scales with
  a seller's report count rather than their row count.

Two guards replace what was deleted, both about the lane's ENDING rather than its pace. A
ceiling moves below every report a tick attempted, so a report WB lists and serves no rows for
— which writes no header and therefore never stops being missing — cannot be asked for once a
minute for ever. And a sweep that shrinks the backlog by nothing ends the lane, while one that
achieved something goes round again for whatever it lost to a timeout. The rule those two
encode is the one a workspace's long history gap came from: a lane may only end on evidence that
nothing is owed, never on the exhaustion of its own reach.

One thing deliberately not done at first: `scripts/backfill_pnl_columns.py` still walked date
windows through `stream_rows_by_period`. It was a one-off run by hand with somebody watching,
and porting it was not what this migration was for — but the client said in its docstring
that nothing scheduled may use that method.

*Both halves of that paragraph are history now.* The history backfill itself walks by period
(above), and `scripts/backfill_pnl_columns.py` was deleted on 2026-09-24 together with
`ingest_finance_report`, `merge_report_headers` and `report_headers` — the header-from-rows
path only it used. A header is written from WB's `list` entry and only after all of the
report's rows, and is refused when WB lists money in a report and none of its rows are held.
A page WB withholds is a failure, not a quiet success.

### 6. Reconciliation against WB's totals

New, and only possible after phase 1. Store the `list` summary per report and compare it with
our own aggregation on every harvest. A mismatch is the alert [`PNL.md`](PNL.md) says we
cannot otherwise raise.

**Landed in two steps.** The comparison was written on 2026-09-22 and called by nothing; since
2026-09-24 it runs whenever a report is booked, feeds `settlement_payout_divergence`, and
`SettlementPayoutDisagreesWithWb` (`backend/docker/observability/alerts.yml`) fires on a
disagreement of one unit of currency or more. The one disagreement it found is resolved — see
the banner.

### 7. Cutover and removal — done 2026-09-24

As planned — kept for the record, with what landed after it:

Behind a setting for one cycle, then delete:

* `WBFinanceClient.fetch_first_row` and the v5 path;
* `SETTLEMENT_REPORT_PATH` from the statistics buckets and from `shared_block`;
* `SETTLEMENT_PACE_CEILING_SECONDS`, the 960 s statistics bucket, the walk's 1000 s queue;
* the settlement-specific escalation margin in `PENALISE_LUA` — **keep the mechanism**, it is
  correct for any endpoint that behaves that way, but nothing will be on the list.

The open question of whether the v5 budget is per token or shared becomes moot on cutover: the
answer stops mattering once the P&L no longer reads that endpoint.

What landed:

* There was no setting and no cycle: the cutover on 2026-09-22 was immediate.
* `WBFinanceClient`, `fetch_first_row` and `clients/finance.py` — deleted.
* `SETTLEMENT_REPORT_PATH` — deleted 2026-09-24. No gate passes `shared_block` any more; the
  mechanism stays in `rate_limit` for a future endpoint that needs it.
* `SETTLEMENT_PACE_CEILING_SECONDS`, `settlement_walk_rate_gate` and
  `wb_statistics_walk_queue_seconds` — deleted with phase 5. The statistics surface's default
  bucket went from 960 s to 60 s on 2026-09-24.
* **The "settlement-specific escalation margin in `PENALISE_LUA`" did not exist.** The item
  misdescribed the code: `_BLOCK_MARGIN = 1.25` and the escalation memory were always generic,
  so there was nothing to delete.
* `record_publication_spread` and `settlement_publication_spread_hours` — deleted 2026-09-24;
  the question they measured is answered (see the banner).

## Risks, in the order they would hurt

1. **A silently wrong field mapping.** Produces a plausible statement. Mitigated entirely by
   phase 2, which is why phase 2 is not optional and not a spot check.
2. **Type surprises on values the sample row had as zero.** Same mitigation; the probe must
   report type divergence, not only value divergence.
3. **Tokens.** One workspace holds a per-surface «Финансы» token. The others hold `unified`
   tokens, which should cover Finance — but that is an assumption, and it must be checked per
   workspace before cutover, not during it.
4. **`reportType`.** `list` returns `reportType: 1` and the docs mention daily as well as
   weekly reports. Pin what the values mean before filtering on them.
5. **`rrdId` paging is not chronological.** A seller on WB's forum documented that across
   report boundaries `rrd_id` is not monotonic by date on the v5 by-period method. Paging by
   report id avoids the problem entirely — which is another reason phase 4 prefers it.

> **Risk 5, measured 2026-09-23 and not reproduced.** One by-period request over an
> eight-report window on one workspace returned exactly our row count for that window and all eight
> reports, with zero `rrd_id` descents and each report contiguous and in date order — a report
> WB had served late sat correctly among them. That does not disprove the claim for re-issued
> or month-split reports, which were not in the sample, but it does mean the by-period form is
> worth many reports a request against one, and that the history backfill was paying that
> difference for a safety nobody had yet shown it needs.
> *It stopped paying it the same day:* a contiguous run now walks by period, and because the
> window books nothing until every page lands and each booked report is checked against WB's
> `forPaySum`, an early stop would surface as a divergence rather than a gap.

## What does not change

The corrections of the preceding days stand on their own and are not part of this: the
per-endpoint analytics buckets, the `/supplier/orders` burst-vs-rate fix, the block margin
and escalation memory, the abandonment horizon, and the rule that a request inside a refusal
is free everywhere except the endpoint we were leaving.
