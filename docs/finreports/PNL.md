# P&L — the method and its proofs

> **Status (2026-07-30): built and reconciled.** The statement is computed from WB's weekly
> settlement detail (`GET /api/v5/supplier/reportDetailByPeriod`) plus the cost price entered
> by the seller. Every block reconciles **exactly** — residual 0.00 — over the whole stored
> history.
>
> **The source changed on 2026-09-22.** WB had switched `reportDetailByPeriod` off on
> 15.07.2026; the weekly detail now comes from finance-api
> (`POST /api/finance/v1/sales-reports/detailed…`, with WB's headers and totals from
> `sales-reports/list`), and on top of it sits a provisional "tail" of daily reports for the
> days no weekly report covers yet. The column names and the whole method below did not
> change; the row-by-row comparison before and after is in
> [`MIGRATION_TO_FINANCE_V1.md`](MIGRATION_TO_FINANCE_V1.md), phase 2. Since 2026-09-24 every
> booked report is checked against WB's `forPaySum` (see "The payout's sign comes from the
> document type, not the operation").
>
> The one input WB does not have is the cost price. Everything else is taken from WB's own
> documents, and nothing is estimated.

This document records what cannot be recovered from the code: **why** the rows are counted
exactly this way. Every statement below was checked arithmetically on a live payload (a full
weekly report) and/or against aggregates over the whole history in the database. Where a
check is impossible, it says so.

---

## 1. What kind of report this is

**A settlement-basis report, not an order-basis one.** A row lands in the period in which WB
*settled* it (`rr_dt`), not the one in which the item was ordered or bought out.

The consequence to understand: **a large share of returns is settled in a different weekly
report from the sale they reverse** — usually a few days later, sometimes weeks later. A week with heavy returns will show negative units for a SKU. That is normal: a small
number of "report × SKU" cells are negative, and most of them are weeks with no sales at all.

That is how it should be. The point of the report is to reconcile with the money that
actually arrived, and a report that keeps rewriting itself is useless for that.

---

## 2. The anchor figure: `ppvz_for_pay`

**«К перечислению за товар» (payout for goods) is never recomputed.** It is
`Σ ppvz_for_pay` — the only figure WB actually settles on.

The verified identity (on «Продажа» and «Возврат» rows):

```
ppvz_for_pay = retail_amount − ppvz_vw − ppvz_vw_nds − acquiring_fee − ppvz_reward
```

On the verified weekly report it holds on **every** such row with a maximum residual of
0.005 (WB's rounding to the kopeck). Over the whole history it holds with two exceptions,
covered in §4 and §5.

### Why the commission is a residual, not a sum

WB publishes its fee twice: `ppvz_vw` unrounded (≈14 decimal places; the VAT-inclusive value
divided by 1.12) and `ppvz_sales_commission` — the same number rounded to kopecks. The sum
of either of them with `ppvz_vw_nds` does not match `ppvz_for_pay` — there is a small
rounding residual every week. A reader who added up the report's rows would not arrive at
the payout.

So the line «Комиссия WB (с НДС)» (WB commission incl. VAT) is derived as a residual:

```
commission = paid − payout_for_sales − acquiring_withheld − agent_reward
```

The block reconciles to the kopeck, and `ppvz_vw` and `ppvz_vw_nds` are stored and used as a
cross-check.

**`ppvz_vw` is stored as `Numeric(18, 10)`, not `(14, 2)`.** Rounded to kopecks it becomes
bit-for-bit equal to `ppvz_sales_commission`, and the identity breaks on a few percent of
rows (measured on one week).

---

## 3. Compensations are counted apart from sales

The commission is derived against the **sales** part of the payout (`ppvz_for_pay` on
«Продажа» minus that on «Возврат»), not against the whole of it.

The reason: WB has separate operations that put money into `ppvz_for_pay` and **into no other
column** — «Компенсация ущерба», «Компенсация брака», «Компенсация подмененного товара»,
«Компенсация потерянного товара», «Добровольная компенсация при возврате» (damage, defect,
substituted-item, lost-item and voluntary-on-return compensations). Over a year these add up
to a noticeable sum.

* Filter the payout on «Продажа» only, and this money **disappears**.
* Derive the commission against the full payout, and it turns into **negative commission** —
  distorting that line by the entire compensation total.

So the report has three lines: «К перечислению за продажи» (payout for sales), «Компенсации
WB» (WB compensations) and their sum — «К перечислению за товар».

### Daily rows live until the day is closed by a weekly report

The daily tail is provisional rows; the weekly report is the document. Since 26.09.2026 the
rule is:

* **The day is closed by a weekly report** — rows still under a daily report number are
  deleted. The weekly report rewrites, under its own number, every row present in both, so a
  row still under the daily number is one WB did not include in the settlement. Cleaned in
  every tick right after the weekly part.
* **WB withdrew a daily report** (absent from the list a day later) — its rows are deleted at
  once.
* **WB changed a daily report** (its totals moved) — the old rows are deleted before the
  re-read, so the database holds exactly what WB serves now. If the re-read fails, the report
  is "forgotten", and the tail downloads it again on the next tick.

### Rows from an uploaded file stand in until the API serves them (since 12.10.2026)

A seller can download «Еженедельный детализированный отчет» (the weekly detailed report) in
their WB account — it appears there hours, once more than a week, before the API serves it —
and upload it with the «Загрузить отчёт» button. The file is a WB document, and its 58 columns
matched the API rows on every row of a full report. What the file lacks:

* **`rrdId`** — file rows are written with a **negative** `rrd_id` from
  `finreports.upload_row_seq`. The sign is the only marker of a file row; by it `holds_report`
  does not count the report as downloaded, and no header is booked over the file.
* **`rr_dt`** — taken from «Дата продажи» (sale date), clamped to the week's bounds. That is
  the operation date on almost every row; the rest are logistics a day or two earlier. The
  week as a whole is exact; the days inside it are approximate until the API arrives.
* **The report number** — only in the file name («…№<report id>_…»), and read from there.
* **The currency** — taken from the workspace's earlier rows.

Only what we lack is written: the file rows are compared, as a multiset, with all our rows for
the week's days, including the daily tail. They match — "already held", nothing is written. We
have nothing — everything is written. We have a part, and all of it is in the file — the
missing rows are added. Otherwise it is a disagreement: nothing is written, and the alert
`SettlementUploadDisagreesWithWb` fires. While an upload stands, the daily tail does not
touch its days. When the API serves the report, booking the header compares the file rows
with the API rows and deletes them — their place is taken by rows with the real id and date;
a disagreement raises the same alert. Code: `services/settlement_upload/`,
`tasks/settlement_upload.py`.

### The payout's sign comes from the document type, not the operation

WB serves `ppvz_for_pay` positive on every row. The direction lives in `doc_type_name`: rows
of type **«Возврат» subtract, all others add**. That is exactly WB's `forPaySum` from
`sales-reports/list`, to the kopeck, on every report in one workspace's history (checked
24.09.2026).

The operation name does not decide the direction. The same operations arrive with both
types:

| operation | seen as «Продажа» | seen as «Возврат» |
| --- | --- | --- |
| «Коррекция продаж» (sales correction) | ✓ | ✓ |
| «Коррекция возвратов» (returns correction) | ✓ | ✓ |
| «Компенсация ущерба» (damage compensation) | ✓ | ✓ |
| «Добровольная компенсация при возврате» (voluntary compensation on return) | ✓ | ✓ |
| «Частичная компенсация брака» (partial defect compensation) | ✓ | ✓ |

What they are shows in the rows of a single order (`srid`). «Коррекция возвратов» of type
«Продажа» arrives when WB cancels a return it had booked earlier, and gives the seller their
money back. A week later WB may book the same return again, now as «Коррекция возвратов» of
type «Возврат», and take the money back — the same amount out and in, with the logistics next
to it corrected by the same pendulum. «Коррекция продаж» of type «Продажа» most often tops up
a sale that was booked with a zero payout.

Until 24.09.2026 the P&L added everything except «Возврат». A rule keyed on the name would have
matched WB on most reports but not all, and the rule "always subtract «Коррекция продаж»"
(which lasted a few hours) was right for exactly one report.

There is one rule, `REFUND_DOC_TYPE` in `constants.py`. The «Компенсации WB» line, the size
breakdown and the report-completeness check (`incomplete_report_ids`) all read it, so the P&L
and the check cannot drift apart.

---

## 4. Acquiring: withheld and invoiced separately

Over the whole history the §2 identity fails on a small set of rows. On almost all of them the
residual **equals `acquiring_fee` exactly**, and every one of those rows has
`payment_processing = «Комиссия за организацию платежа с НДС»` (payment-arrangement fee incl.
VAT).

Conclusion: WB **does not withhold** this fee from the payout; it invoices it separately. The
other three `payment_processing` values («Перевыставление эквайринга», «Компенсация платёжных
услуг», empty) break the identity on only a handful of rows.

So acquiring is split:

| line | formula |
|---|---|
| «Эквайринг (удержан)» — acquiring, withheld | `Σ acquiring_fee` where `payment_processing ≠` the marker |
| «Комиссия за организацию платежа» — payment-arrangement fee | `Σ acquiring_fee` where `payment_processing =` the marker |

The second is **for reference only**; it is subtracted nowhere. Count it as withheld and
acquiring is overstated by its whole amount while the WB commission is understated by the
same — with the total unchanged. Exactly the case where the report reconciles and two of its
lines are still wrong.

The remaining handful of rows (thousandths of a percent of the payout) is unexplained and
falls into the commission line as part of the residual.

---

## 5. A negative commission is not an error

Over a whole year the WB commission can come out **negative**: WB paid the seller more than
the buyers paid.

The mechanism: WB funds SPP (its discount to regular customers) out of its own fee, and
when the discount exceeds the commission rate, the fee goes negative. In one week of 2026
`ppvz_vw` was negative on about a quarter of the rows, and on some rows
`ppvz_for_pay > retail_amount`.

The report shows this as is and adds a caveat — otherwise a reader will assume the sign is
flipped.

---

## 6. Units: `quantity` is a classifier, not a measure

`quantity = 1` on every «Продажа» and «Возврат» row in the whole history (min = max = 1),
and `0` on every expense row. There are no negatives anywhere: the sign is carried by
`supplier_oper_name`, not by the value.

**`SUM(quantity)` without a filter is forbidden.** The operation «Возмещение издержек по
перевозке/по складским операциям с товаром» (reimbursement of transport / warehouse costs)
carries `quantity = 2` on **all** of its rows — it is a placeholder, not units: those rows have
`nm_id = 0` and empty `barcode`, `sa_name`, `office_name`. Summing would add two phantom units
per such row (e.g. 100 000 filler rows → 200 000 units that never existed) and understate every
per-unit figure in the report.

Compensations (§3) carry `quantity = 1`, but their `srid` matches no sale — this is money
without any movement of goods, and they are not counted as units either.

---

## 7. Returns arrive with a POSITIVE sign

`retail_amount`, `ppvz_for_pay`, `acquiring_fee`, `quantity` — on «Возврат» rows everything is
positive, without a single negative value in the verified week. Each such column is
**subtracted explicitly**.

Add them to sales instead and a week's payout comes out tens of percent too high — an
overstatement that still looks like money.

Separately: «Выручка по цене продавца» (revenue at the seller's price) and «Оплачено
покупателями» (paid by buyers) subtract returns **on the same base**. Subtract returns at
their after-SPP amount from the before-SPP revenue, and the «Скидка WB» (WB discount) line is
overstated by the SPP of the returns themselves.

---

## 8. Expense lines are not filtered by operation

Aggregating every money column by every operation over the whole history showed: **each
column is filled by exactly one family of operations and is identically zero on all others.**

| column | operations |
|---|---|
| `delivery_rub` | «Логистика», «Коррекция логистики» |
| `storage_fee` | «Хранение», «Коррекция хранения», «Пересчет хранения» |
| `acceptance` | «Платная приемка», «Пересчет платной приемки», «Обработка товара» |
| `penalty` | «Штраф» |
| `deduction` | «Удержание» |
| `rebill_logistic_cost` | «Возмещение издержек по перевозке» |
| `ppvz_vw`, `ppvz_vw_nds` | «Продажа», «Возврат» — **and «Возмещение издержек по перевозке»**, see below |
| `additional_payment` | never filled (0.00 over the whole history) |

So the expense lines are `Σ` of the column **with no filter by operation**. That is not only
simpler but safer: if WB introduces an operation tomorrow that charges storage, it lands in
the storage line instead of vanishing.

The operation filter is needed for revenue, units and payout — where the operation decides
the **sign** — and for two more columns where WB breaks its own rule.

**`ppvz_vw` and `ppvz_vw_nds` are not filled by sales alone.** «Возмещение издержек по
перевозке» reuses them to express the VAT split of its own charge: on those rows `ppvz_vw` and
`ppvz_vw_nds` are negative and add up to the amount in `rebill_logistic_cost`. That is not a
commission at all.

These two columns break down the commission line, and that line is derived as a residual over
the **sales** part of the payout — so they must be summed over the same rows. Summed over "all
operations except returns", the «в т.ч. НДС комиссии» (of which VAT on commission) sub-line was
printed wrong over the whole history and had **the wrong sign** in some weekly reports (a
negative VAT under a positive commission). The total still reconciled — only the reference
sub-line was wrong, which is exactly the figure someone quotes when asked "how much VAT did WB
take".

An unknown operation does not pass silently either: `unclassified_opers` compares the values
seen against the taxonomy in `constants.py` and reports the difference in `notes`.

---

## 9. Logistics: two legs and cancellations

`delivery_amount` and `return_amount` are **counters, not money**. On a «Логистика» row exactly
one of them is set: over the whole history there is no row with both or with neither. That is
what splits `delivery_rub` into "to the customer" and "back". Reading either one as roubles
doubles the largest expense item.

But **«Коррекция логистики» rows have neither counter set** — all of them. That is money on a
logistics row belonging to neither leg, so it gets its own third bucket. Folding it into "to
the customer" so the two sub-lines add up to the total would present corrections as delivery
to buyers: three honest buckets beat two that add up.

The breakdown by `bonus_type_name` within a week reconciles to the logistics total. The
reasons WB uses:

| reason | meaning |
|---|---|
| «К клиенту при отмене» | to the customer, order later cancelled |
| «К клиенту при продаже» | to the customer, sold |
| «От клиента при отмене» | back from the customer after a cancellation |
| «От клиента при возврате» | back from the customer after a return |
| «Возврат брака (К продавцу)» | defective item returned to the seller |
| «Возврат неопознанного товара» | unidentified item returned |

**On the account this was built against, the majority of the logistics bill paid for
cancellations — trips that brought in no revenue at all.** That was the report's main finding
for that seller.

---

## 10. Advertising is in the report

The «Удержание» (deduction) operation is not "other". The overwhelming majority of what it
withholds carries a `bonus_type_name` containing «Продвижение» (promotion) — that is,
**advertising**. Smaller parts are the «Джем» subscription and delivery of transit supplies.

So «Удержания» are split by a substring of `bonus_type_name`. Substring matching is fragile by
nature, but safe here: an unrecognised label falls into «Прочие удержания» (other deductions) —
it may land in the wrong bucket, but it never disappears from the total.

A caveat that must be on the page: advertising paid **from the WB balance** does not appear in
the weekly report. The report only shows advertising withheld from the payout.

---

## 11. `Возмещение издержек по перевозке` — the sign is not confirmed

`nm_id = 0`, and almost every row shares its `shk_id` with a «Логистика» row. The money is in
`rebill_logistic_cost` — **and in `ppvz_vw` / `ppvz_vw_nds`**, where WB puts the VAT split of
the same charge (see §8). WB stopped this operation in **May 2025** — it does not appear after
that.

The report treats it as a **deduction** (subtracts it). The grounds: the name ("reimbursement
of costs … with goods"), the pairing with logistics, a small average size of a few units of
currency per row, and the position of this line in the deductions block of WB's own report.

**This is not verified against a total printed by WB.** The line is shown on its own and never
folded into another, so that an error would be visible. The exposure is a low single-digit
percentage of logistics. How to check: take a report from the window before May 2025 that has
many such rows and compare the reconstructed total with the footer of WB's XLSX.

---

## 12. Agent VAT — for reference

`agency_vat = round(retail_amount × 0.1803, 2)` — exact on all but a couple of non-zero rows
of the verified week (those WB serves as zero with a non-empty amount — a data anomaly, not a
rule). That makes it about 18 % of gross sales.

**It is not part of the calculation.** The §2 identity closes without it with a residual of
0.005, while the value itself is five orders of magnitude larger — subtracting it anywhere
would break the whole block. It is stored verbatim and shown on a reference line, so that the
figure is not mistaken for a lost expense.

---

## 13. Cost price — the only unverifiable input

Stored in `finreports.product_cost_price`, keyed on `(workspace_id, nm_id)`.

**The key is `nm_id`, and that is a choice, not a convenience.** `sa_name` is not stable: some
`nm_id`s carry two or more vendor codes over their history, including variants with broken
UTF-8. `barcode` is even less suitable: sellers reuse barcodes between cards, so one barcode
can point at two or three different `nm_id`s.

One price per `nm_id` ignores the size (a SKU can have many), and that is a deliberate
simplification — consistent with sellers stating their cost per model.

### Coverage is part of the figure, not a footnote

Cost prices rarely cover the whole catalogue: some of the SKUs a seller prices have never sold,
and some that sell have no price yet.

A SKU without a cost price **enters neither COGS nor the coverage denominator** — the margin
is computed only over what is actually backed by a price, and the coverage share is shown next
to it, both on the tile and in `notes`.

Coverage is weighted by units, so it is concentrated: a few prices for the top-selling SKUs
usually cover most of the units, while pricing every new card changes little.

A cost price in a currency other than the settlement currency is **dropped, not converted** —
the SKU counts as uncovered. Converting at an invented rate would produce a plausible margin
that is wrong by the size of the rate.

---

## 14. What the report does not include

Explicitly marked as not included:

* taxes (the seller's simplified-tax / VAT) — the weekly report has none at all;
* salaries, rent, packaging, external logistics to the WB warehouse;
* advertising paid from the WB balance (§10);
* «Доплаты» (additional payments) — the `additional_payment` column is 0.00 over the whole
  history. Its sign is pinned by a test all the same: nothing in the data would reveal it being
  flipped.

That is why the bottom line is called «Маржинальная прибыль» (contribution margin), not «Чистая
прибыль» (net profit).

---

## 15. How it is verified

| level | what it proves |
|---|---|
| `tests/unit/finreports/test_pnl_statement.py` | Arithmetic against a synthetic weekly report whose rows reconcile to its footer by construction; the blocks add up with no tolerance; mutation-checked (adding returns, commission against the full payout, separate acquiring as a deduction, COGS clamping, the sign of top-ups — each is caught by its own test) |
| `tests/component/finreports/test_pnl_routes.py` | Transport: the default window by the Moscow day, grouping validation, tenancy of reads and writes, cost-price bounds |
| `tests/unit/finreports/test_sku_report.py` | The SKU row's arithmetic: «к перечислению» (payout) net of the SKU's own deductions, profit `None` without a cost price, `None` ≠ 0 for orders/advertising with no coverage, negative COGS in refund windows |
| `tests/unit/finreports/test_settlement_ingestion.py` | `TXN_UPDATE` covers the whole table (otherwise a repeated harvest would "successfully" leave columns at zero); the mapper writes every column; the period comes from WB, not from min/max `rr_dt`; the precision of `ppvz_vw` |
| `tests/unit/finreports/test_settlement_streaming.py` | Walking a report does not accumulate pages (checked by counting live objects through `gc` — no assertion would see it otherwise); the period of a report whose rows fell on different pages stays what WB declared; a break mid-walk is not swallowed |
| `tests/integration/finreports/test_harvest_is_atomic.py` | The real `harvest_workspace` on a real PostgreSQL: a request that fails mid-page leaves none of its rows, while batches committed before the break and earlier requests stay — and the report still counts as not fully fetched; the client inside a transaction retries on a shorter ladder than the standard one. (Until September 2026 this checked a SAVEPOINT around the whole walk — see "A settlement window is written whole or not at all") |
| `tests/unit/finreports/test_wb_labels_are_pure_cyrillic.py` | No WB label used in a comparison contains Latin look-alike characters |
| `tests/integration/finreports/test_pnl_caveats.py` | COGS counts only SKUs with a cost; a cost in the wrong currency is dropped, not converted; advertising is broken out of deductions; `test_the_vat_sub_line_belongs_to_the_commission_it_sits_under` — the «в т.ч. НДС» sub-line is summed over the same rows as the line above it (guards §8); an unknown operation becomes a caveat |
| `tests/integration/finreports/test_pnl_reconciles.py` | The aggregation itself in a real PostgreSQL: the revenue block reconstructs the settled payout, the residual commission matches the one WB published, the buckets sum to the total for any grouping, another tenant's rows are invisible, the filler operation's `quantity` never becomes a unit, a compensation raises the payout without becoming revenue; the payout's sign comes from `doc_type_name` |
| `tests/integration/finreports/test_sku_report_reconciles.py` | Σ rows + «без привязки» (unattributed) == the window total with no tolerance; account-level money is not smeared across SKUs; the monitoring loaders really deliver orders and advertising per SKU |
| `tests/integration/finreports/test_sizes_match_the_article.py` | The sizes sum to the SKU row in every shared column (§17.1) |
| `tests/integration/finreports/test_rollup_matches_the_detail.py` | The rollup reports what the detail reports, and every way it can go stale is caught (§15.1) |

Reconciliation on live data: the revenue-block residual, the deductions-block residual and the
"sum of buckets − total" difference are **0.00** on every window checked — a single week,
whole years and the whole history.

---

## 15.1. The settlement rollup — and why it can be trusted

The detail table is far larger than PostgreSQL's `shared_buffers`, so a window covering most
of it is read by a parallel **seq scan**: several seconds a pass, measured. The same rows fold
into groups keyed by (workspace, report, day, SKU) — about forty times fewer, and entirely in
cache. Hence `finreports.settlement_daily_rollup`.

**It is a cache, and no read trusts it.** Before returning anything, the query asks the detail
how many rows each day of the window has — an index-only scan, an order of magnitude less I/O
and time than the full read — and compares that with how many rows the rollup believes it
summed. Days where the numbers match are read from the rollup; days where they differ or are
missing are recomputed from the detail and rewritten.

Three consequences, which are the whole point:

* an empty, stale or hand-damaged rollup costs time, not correctness;
* there is no build step, no harvest hook and no watermark to maintain: the first read of a
  window pays, the rest do not;
* a day WB filled in retroactively (and it does back-date reports) is caught by its row count,
  not by a "this day was already counted" flag.

**Correction 2026-09-24: a row count alone is not enough.** A row rewritten in place does not
change the count, and that is the normal path, not an edge case: the weekly report overwrites
every row of the daily tail under a new `report_id`, and a re-issued daily report arrives with
new amounts on the same `rrd_id`s. The rollup was serving the old figures. Now the only write
path for the detail (`LogisticsTransactionRepository.bulk_upsert`) deletes, in the same
transaction, the rollup of every affected day, and the next read rebuilds them. The row-count
check remains for everything that bypasses it: a rollup truncated or edited by hand, a day
that lost rows.

The key carries `report_id` alongside `rr_dt`, so all five cuts derive from one grain: total,
day, week (report), month and SKU. The rollup's columns are literally the same expressions as
the direct aggregate, sliced from one list, so they cannot diverge: a test compares both paths
on all five cuts.

The one divergence allowed on purpose: the window's currency is taken as the mode over rollup
GROUPS, not over detail rows. They differ only for a workspace that settles in two currencies
within one day — which WB does not do.

---

## 16. Operations

The P&L columns were added by migration `be09d50ae5ff` **as zeros** — a migration cannot
invent facts it never harvested. They were filled by `scripts/backfill_pnl_columns.py`, which
re-requested the history in windows and upserted by `rrd_id`.

**The script was deleted on 2026-09-24**, together with the "header from rows" path that only
it used. It had done its job: on the workspace checked, no «Продажа» row was left without revenue (checked
2026-09-24), and a new workspace gets its history through the ordinary backfill, which writes
every column at once. Keeping a manual date walk that no scheduler calls would have meant
keeping a second write path for money without a single test.

### A settlement window is written whole or not at all

The harvest **does not download a window in full; it writes it page by page as it arrives**
(10 000 rows a request). It was not always so: a window used to be gathered into one list, so
peak memory depended on how much the seller had sold, grew on its own, and one day hit the
cgroup limit — the worker was killed mid-walk. Now the peak is set by the page size, not by
the history.

The price is that a break mid-walk happens when some rows are already written. So the walk ran
inside a SAVEPOINT: a failed walk rolled back entirely, while the other sources of the same
harvest committed as before. **Half a weekly report in the database is not an error anyone
sees, it is a quiet week** (§1) — exactly the class of discrepancy this whole document is
written against. The transaction stayed open for the duration of the HTTP walk, so the finance
client had a shortened retry ladder — PostgreSQL kills a session that sits idle in a
transaction for 5 minutes.

**That was the design until September 2026; the mechanism is different now, the goal the
same.** A page is now up to 100 000 rows (what finance-api serves), parsed as a stream while
the body arrives, and **each batch is committed at once** — one transaction for the whole page
held fifty batches and once killed a worker on memory. The token is taken before the session
opens, so the transaction never waits on WB. Integrity comes not from a rollback but from the
order of writes: rows are idempotent (upsert by `rrd_id`, the cursor moves only after a
successful request), and **the report header is written last** — from the `sales-reports/list`
entry and only once all its rows have arrived. No header — the report counts as not fully
fetched and is requested again, so a half-written report never looks complete. A report in
which WB shows money while we hold none of its rows gets no header at all, and a booked one is
checked against WB's `forPaySum`.

Cost prices are the seller's own figures and are entered on the page: one at a time, or in
bulk through the xlsx round trip — export the per-SKU statement, fill in the «Себестоимость за
1 ед.» column, upload the same file back (`services/cost_price_workbook.py`,
`services/cost_upload_parser.py`). Each figure records where it came from (`source`), so a
number typed by a person is never indistinguishable from one taken from WB's documents.

---

## 17. Per-SKU report (`GET /v1/finreports/pnl/skus`)

A cut of the same table by `nm_id` over an arbitrary date window. The rules that make it
reconcilable:

* **Σ rows + «Без привязки к артикулу» (not attributed to a SKU) = the window total, with no
  tolerance.** A SKU's row contains only its own settlement rows; account-level money
  (storage, acceptance, «WB Продвижение» invoices, the filler operation) is NOT smeared across
  SKUs by any key — it sits on a separate row. The reference spreadsheet the seller used before
  («Финтетрадь») does smear it — which is why its per-SKU «Чистая прибыль» cannot be
  reconciled, while ours adds up to the total page by page.
* A row's «К перечислению» = `ppvz_for_pay` of its rows minus its own logistics and penalties —
  the same formula as the window's «Итого к оплате», applied to a subset.
* **Every share of revenue is taken of «Продажи» (sales)** — the seller's prices before SPP,
  net of returns: logistics share, DRR, margin %, in the SKU row, in «Итого», in the sizes, in
  the card at the top and in the statement lines. Until 26.09.2026 the table divided by
  «Оплачено» (after SPP) while the card divided by «Продажи», and one page showed two
  logistics shares. The seller's price was chosen because SPP is WB's discount at WB's expense,
  and it changes every week: measured against «Оплачено», the logistics share rose whenever WB
  raised SPP although the seller's costs had not changed. WB's payout and commission are also
  computed from the seller's price. Example: price 1000, SPP 20 %, logistics 150 — that is
  15 % of sales (and would be 18.75 % of the paid amount). The colour thresholds
  (`pnlThresholds.js`) were tuned for the old base and read softer on the new one — they are
  worth re-checking against live figures.
* **Since 01.10.2026 the user picks the base** — the toggle «Цена селлера — до СПП» / «Цена
  реализации» (seller's price before SPP / sale price), as on the summary page
  (`frontend/src/modules/finreports/priceBase.js`). The reason: «Продажа» in WB's report is
  the sale price, and a card showing the seller's price could not be checked against it by eye.
  The seller's price stayed the default, for the reason above. Every figure divided by revenue
  follows the base: revenue itself, the average receipt, the logistics share, DRR, margin % —
  in the cards, the table, «Итого», the phone cards and the size breakdown. The payout, profit
  in money, ROI (profit over cost price) and SPP do not move — SPP is the very difference
  between the bases. The front end recomputes the shares from the row's sums rather than taking
  the backend's `*_pct`: one division whatever the base. The average receipt follows the base
  too; it used to be the buyer's price even with the base set to the seller's price. The
  highlight thresholds were tuned for the seller's price and fire more often on the sale price.
* **Three columns do not come from the settlement**, and all three sources are younger than
  the settlement history: «Заказы» (orders) — from the monitoring funnel, «Реклама»
  (advertising) — from the Promotion API's campaign statistics (in the settlement itself
  advertising appears only as account-wide invoices without `nm_id`), «Бонусы» (bonuses) — from
  the write-off log `GET /adv/v1/upd` (see §18). Outside its coverage a column returns `None`
  and a caveat, not zero: "we don't know" and "there was none" read differently on a report.
  Access is only through `monitoring/contract.py` (`load_orders_by_nm`, `load_ad_spend_by_nm`,
  `load_ad_bonus_by_nm`, `*_coverage`).
* «Чистая прибыль» (net profit) = payout − cost price − advertising **net of bonuses**; without
  a cost price it is `None`, never "the profit if the goods were free". ROI is computed from the
  same figure (§18). The table had ROMI until 29.09.2026; it was removed at the seller's
  request.
* **A SKU's «Выкуп, %» (buyout rate) is WB's «Процент выкупа» from the funnel (since
  01.10.2026).** Buyouts ÷ (buyouts + refusals) for orders PLACED in the window (funnel days
  are order dates), only over days that have passed the cohort pass: a day with
  `cancel_count IS NULL` does not know its refusals yet and enters neither the numerator nor
  the denominator (otherwise it would look like 100 %). WB's own account and the monitoring
  matrix count it the same way. The last ~3 weeks of a window are still maturing — a property of
  WB's figure itself, not our error. The loader is `load_buyouts_by_nm` in the monitoring
  contract; the row carries `buyout_units` / `decided_units` so «Итого» divides sums instead of
  averaging percentages.

  Before 01.10 the column was a stub marked "temporary": units sold ÷ deliveries to the buyer by
  SETTLEMENT date over the same window. That divides two different heaps of goods — what was
  bought out this week may have shipped last week — so on a short window the figure is noisy and
  does not match WB's account. **The sizes keep that measure** (§17.1,
  `test_sizes_match_the_article`): the funnel has no sizes, the report rows do, and there is no
  other way to measure a size's buyout. So a SKU's buyout and the sum of its sizes' buyouts now
  legitimately differ.
* **The «Итого» row takes advertising from WB's invoice** (the owner's decision of
  2026-10-02). WB charges for advertising in two forms, and it is the same money: the weekly
  invoice «Оказание услуг «WB Продвижение»» withheld inside the payout, and the spend from the
  campaign statistics, dated by impression days. A SKU row has no invoice — it arrives without
  `nm_id` — so the SKU row subtracts the spend net of WB's bonuses. The total is the only place
  that has both, and until 02.10 it replaced the invoice with the spend; now total = payout −
  cost price, with the invoice already inside the payout. «Реклама» in the total = invoice +
  bonuses, «Бонусы» = Σ bonuses, the difference = the invoice. Subtracting the spend from a
  payout already net of the invoice takes the advertising off twice. Invoice and spend differ
  because of dates (noticeably week to week, much less over several weeks), and while advertising was billed in roubles also because of the rate date — WB
  converted the rouble invoice at the rate of the day the document closed, we convert the spend
  at the rate of the impression day. «К перечислению» is untouched, so the check of Σ rows +
  «без привязки» against WB's payout stays intact.
* A row's percentages are shares of its own net revenue (sales − returns), as in the
  reference spreadsheet.
* **«Логистика на 1 выкуп» (logistics per buyout)** (since 12.10.2026) = all of the row's
  logistics (outbound, return and other) ÷ units sold, without subtracting returns — like WB's
  buyout. Computed on the front end from the row's sums; for «Итого» and groups — from sums,
  not as an average. Sizes have it too. Why: the price of one trip within a SKU hardly depends
  on the size, while the price per sale does — strongly, often several-fold between sizes of
  one SKU — because the trips that ended in a refusal are paid for by the unit that sold. A
  size's poor buyout shows here in money. «Логистика на 1 доставку» (logistics per delivery)
  remains only in the `/sizes` response.

---

## 17.1. A SKU broken down by size (`GET /v1/finreports/pnl/skus/{nm_id}/sizes`)

The same set of settlement rows, grouped by `ts_name` within one SKU. It exists because an
"on average profitable" SKU is a common description of a size grid where half the sizes carry
the rest, and the SKU row does not show it.

* **Every row WB bills carries a size.** Measured on one workspace over a quarter: every
  «Логистика», «Продажа» and «Возврат» row carries `ts_name`; only a few account-level
  «Хранение» / «Удержание» rows arrive without a size, and those do not belong to a SKU anyway.
  So the breakdown is a regrouping of the SKU's own rows, not an allocation: **Σ sizes = the SKU
  row, with no tolerance** (`test_sizes_match_the_article` — two copies of the SQL on the same
  rows; on 10.10.2026 the same was checked on the same workspace over several windows from a week to a
  quarter, every money and unit column to the kopeck). A size's «К перечислению» is computed by
  THE SAME formula as the SKU's — otherwise the sum would only match by eye.
* **A size's «Выкуп» is measured by logistics legs, not orders.** The funnel has no size at
  all, and the forward leg `delivery_amount` is the only record that an item reached the buyer,
  and it carries the size. The «К среднему» column (deviation from the SKU's buyout, in p.p.)
  was removed on 26.09.2026: the buyout itself stands next to it, and it repeated it in other
  words.
* **There is no profit or margin in the breakdown** (since 26.09.2026). The Promotion API ties
  spend to `nm_id` and knows nothing of sizes. Splitting it by an estimate (by deliveries or by
  revenue) is possible, but that would be a model, not a report, and a size's margin, by the
  seller's decision, is not that important. The breakdown compares how sizes sell: units,
  buyout, price, revenue, logistics, payout. The cost price left together with the margin.
  Profit stays on the SKU row.
* **«Цена» (price) is the seller's price before SPP per unit bought out**, on the same base as
  «Выручка» next to it: price × units = revenue. It used to be the buyer's price after SPP, and
  the row stopped adding up. SPP is not shown in the breakdown: WB changes it by day and by
  buyer, so a difference between sizes only tells you on which days they were bought.
* **«Логистика на 1 доставку»** — all of the size's logistics divided by deliveries to the
  buyer. Return trips fall on it too, so a size with a poor buyout is more expensive here.
* Read from the DETAIL, not the rollup: the rollup is keyed by day × SKU and stores no size,
  and widening it for a cut that is opened one SKU at a time would mean a three times larger
  index on every page load. With a filter on one `nm_id`, the pass over the detail is covered by
  `ix_logistics_txn_nm_id_rr_dt`.
* **Sizes have no «Итого» of their own** (since 10.10.2026, the owner's decision). It repeated
  the SKU row in everything except the buyout, which is measured differently for sizes — and
  looked like a discrepancy. On screen the sizes are rows of the same table under the SKU, in
  the same columns; the columns a size does not have (orders, SPP, cost price, advertising,
  DRR, bonuses, ROI, profit) are empty. «Логистика на 1 доставку» stays in the API response, but
  the table does not show it: the SKU has no such column.
* Loaded on click when a row is expanded, not together with the table: e.g. a report of forty
  SKUs has some 400 size rows, and people look at one or two.

---

## 18. WB bonuses: advertising the seller did not pay for

**Verified live on 2026-09-15 on one workspace.** WB pays for part of the advertising
out of a bonus pool («Кэшбэк», up to 50 % of a write-off), and until this change such
impressions were counted as the seller's money — DRR was overstated, ROI and margin
understated.

The scale was material: a substantial share of a month's write-offs was bonus money. On the
affected SKUs the bonus covered a third to a half of the spend — enough to turn a clearly
negative ROI into a break-even one, which is the difference between "switch the card off" and
"keep it".

### Why neither of the two sources showed it

* **The settlement report has no bonuses and cannot have them.** «Кэшбэк» rows have
  `updNum = 0` — no document number, so WB issues no invoice for them, and the line «Оказание
  услуг «WB Продвижение», документ №…» never appears for them. Checked: every cashback row over
  two months had `updNum = 0`.
* **In `fullstats` they are inside `sum`, with no breakdown.** Reconciled by campaign: `upd` and
  `fullstats` over the same campaigns agree to within a fraction of a percent. So spend paid
  with bonuses sits in our figures as ordinary expense.

At the same time, every "who funded the discount" column in the detail itself is empty —
`supplier_promo`, `seller_promo_discount`, `loyalty_discount`, `product_discount_for_report`,
`cashback_amount` are 0.00 on every row of the history. Looking for bonuses there is pointless.

### The only source is `GET /adv/v1/upd`, and it has three traps

| trap | what happens if it is ignored |
|---|---|
| `updNum = 0` on every bonus row | deduplicating on it collapses a month into one row — a month of bonuses read as a single write-off |
| `currency` varies within one window (RUB and KGS rows on the same account in the same month) | summing `updSum` adds different currencies |
| no `nmId` — a write-off belongs to a campaign | splitting it across SKUs is only possible with a model |

So `monitoring.advertising_write_off_daily` keeps the grain
`(Moscow day, campaign, paymentType, currency)` and does not store `updNum` at all.

### The split across SKUs is a model, and it is locked in one function

`load_ad_bonus_by_nm` divides a campaign's bonus among its SKUs in proportion to the
`fullstats` spend **over the same window**. Four rules make it fit for a report:

* **A window, not a day.** Write-offs come in batches (one large row late in the evening), and
  a daily split would put the campaign's whole bonus on the SKUs that happened to run in the
  evening. Over a window the two sources agree to ~0.1 % per campaign.
* **Never across campaigns.** A campaign's bonus reaches only its own SKUs.
* **Clamped to the SKU's own spend.** A write-off that fell into the window while its spend
  stayed outside it would otherwise print a negative advertising cost.
* **Matched to the spend, not to the payout.** A campaign's bonus and spend are in that
  campaign's currency, so the split within a campaign is single-currency. Before the account's
  switch in August 2026 `upd` wrote RUB, after it KGS, and by campaign it agrees with
  `fullstats` on both sides of the switch. The first version filtered the log by the
  **settlement currency** and so lost a large share of the real bonuses on July–August windows.
  The currency is stored (it is what WB said).

  **Correction 29.09.2026: the August switch was not a rename but a real move of the
  advertising account to KGS.** This paragraph used to call it a "rename" and claimed the
  amounts did not change. The proof of the opposite is the «WB Продвижение» invoices in the
  report itself. Before the switch, invoice = rouble `upd` write-offs × the Bank of Russia rate
  on the document's closing day, to the kopeck. After it, the invoice equals `upd` one to one.
  The currency is fixed for a campaign when it is created. Old campaigns still answer `RUB` in
  `fullstats` (there is a `currency` field there; our harvest does not store it). The amounts
  did not jump at the boundary only because the exchange rate that day was close to one.

  The consequence for this report: **before the switch «Реклама» and «Бонусы» are in roubles
  while the payout is in soms.** Net profit, ROI and DRR in such a window subtract and divide
  different currencies. There is no conversion at a rate — that is a decision. Instead the
  report shows a caveat whenever a window's advertising was written off in a currency other
  than the settlement currency. The advertising currencies are the union of the currency marks
  of the cash and bonus `upd` rows across the workspace's campaigns.

A bonus of a campaign that has no spend rows in the window is dropped: there is nothing to put
it on, and inventing a SKU is worse than not showing it.

### What the bonus changes, and what it does not

It changes «Чистая прибыль» and ROI (ROMI, which divided by the money invested, was removed
from the report on 29.09.2026).

**It does not change «К перечислению» — and that is not an omission.** That is WB's own
settlement figure and the anchor of the "Σ rows + unattributed = window total" check. A bonus
write-off is not in the payout at all (no document — nothing to withhold), so there is nothing
to change there, and changing it would break the invariant this whole document is written for.

«Реклама» stays gross: the seller checks it by eye against their WB account.

### Matching `paymentType` is an allowlist, and the direction is chosen on purpose

An unknown label counts as the seller's money, so a rename at WB returns the behaviour to what
it was before (an overstated DRR). The opposite default — "unknown = bonus" — would subtract
real money and overstate profit, an error nobody catches. An unrecognised label is reported in
`notes`, so a silent fallback is heard.

### Operations

The nightly harvest keeps the last 7 days fresh; history is filled in by
`scripts/backfill_history.py` (that phase runs **after** fullstats — otherwise the bonus has
nothing to land on). The window is a month per request and WB serves at least two years back,
so two years of history cost about two dozen requests.

The bonus pool is visible in `GET /adv/v1/balance` → `cashbacks[]` (`sum`, `percent`,
`expiration_date`). **Accruals are not in the API**: `/adv/v1/payments` answers 204 for both
months checked, and `upd` has only write-offs. So the bonus share varies widely from day to day
and no coefficient can be hard-coded — the pool also expires by date.
