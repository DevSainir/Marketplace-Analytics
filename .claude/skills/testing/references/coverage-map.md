# Current tests — what is covered, and what deliberately is not

The rules that govern the suite are in this skill's `SKILL.md`, and where each tier's boundary
sits is in `tier-contracts.md`. This file answers the two questions the test tree cannot answer
by itself: **what does each tier own**, and **which gaps are on purpose**.

It carries no test counts. Counts drift the moment someone adds a case, and
`pytest --collect-only -q` / `vitest --run` answer that question exactly whenever it is actually
asked. Update this file when coverage changes *shape* — a new area covered, a gap opened or
closed — not when a file moves.

UI labels are quoted in Russian, as the user sees them, with the English meaning beside the
first mention.

---

## 1. Backend — `backend/tests/`

### Shared scaffolding

| File | Purpose |
| --- | --- |
| `conftest.py` | Applies the tier marker from the directory; `settings_override` restores the settings singleton; lowers the bcrypt work factor session-wide |
| `support/auth.py` | Signed-token minting, header builders, `make_user`, cached password digest |
| `support/fakes.py` | Hand-written in-memory repositories (users, refresh tokens, workspaces, workspace tokens) |
| `support/wb_payloads.py` | Canned WildBerries envelopes, copied from observed responses |
| `component/conftest.py` | The real app over ASGI, dependency-override helper, in-memory rate-limit store, database tripwire |
| `integration/conftest.py` | Test-database provisioning, per-test rolled-back transaction, Redis on index 15, auto-skip |

### `unit/` — pure business rules

* `core/` — password hashing and the bcrypt ceiling; access-token policy; the startup hardening
  guard, **including which environments may publish their own API surface** (`/docs`, `/redoc`
  and `/openapi.json` are a `local`-only affordance; every internet-reachable environment
  withholds them); DSN encoding; UUIDv7 ordering; the Moscow vs operating clocks; Fernet
  encryption.
  Also **the demo** (`test_demo_seed.py`, `test_demo_stack.py`): the fabricated shop
  `make demo` writes is a pure function of the calendar date, so a re-seed leaves every settled
  day as it was; its tables agree (the funnel contains its ads, every sale satisfies WB's payout
  identity, every report states the payout its rows add up to); and the demo stays a Compose
  project of its own, on loopback, with the plain-HTTP nginx and no scheduler.
  Also the **client address** a per-IP control is allowed to key on (`test_client_ip.py`): the
  address the proxy wrote beats a client-chosen forwarded chain, and anything that is not an IP
  is refused rather than becoming a counter key an attacker can mint at will.
  Also the **resource bounds** that keep one account from costing the platform arbitrarily
  (`test_upload_caps.py`, `test_task_time_limits.py`): an upload is refused *while* being read,
  so the peak is the ceiling and not the file; and every Celery task has a deadline whose soft
  half fires first — the hard half SIGKILLs, and `task_acks_late` would then redeliver, so a
  task that hit the hard limit first would loop forever.
  Also the **Redis single-accessor rule** (`test_redis_single_accessor.py`): the private client is
  read only by `get_redis`, no other module names it, and no other module constructs an async one.
  It exists because the component tier's fakes hang off that one seam, so a caller that reaches
  past it reaches a live Redis and fails as `Event loop is closed` — twice, before this test.
  Also the **architecture rules themselves** (`test_module_boundaries.py`: no horizontal imports,
  every contract's `__all__` resolves, the 500-line limit) and **Celery loop hygiene**
  (`test_task_loop_hygiene.py`: no task may call `asyncio.run`, which strands pooled asyncpg
  connections on a dead loop and kills the *next* scheduled task).
  Also **no loop-bound state outlives a task**: `test_redis_client_per_loop.py` (every event
  loop gets its own Redis client, and a client swapped in through `_redis` still serves every
  loop) and `test_no_loop_bound_state_outlives_a_task.py` (no import-time `asyncio` Lock,
  Semaphore, Event…, and no `@lru_cache` around `get_redis()`). A pool's `asyncio.Lock` bound to
  one task's loop once cost a whole day's price snapshot.
  Also **the night ends by 06:30 MSK** (`test_nightly_work_ends_before_the_workday.py`): every
  beat entry firing before 07:00, and the harvest and cohort pass wherever they sit, ends by
  06:30 at its measured worst-case runtime, and the cohort pass starts after the harvest's.
  The runtimes are measurements from the worker log; re-measure them as workspaces are added.
  Also the **fail-open degradation ledger** (`test_degradation_alerting.py`): 500 failing
  requests collapse to one record, an ongoing outage still heartbeats, two controls down at once
  raise their own louder event and one never does, and — the case that matters most — the real
  `consume_budget` against an unreachable Redis still returns `True`, because a silent slide into
  fail-*closed* would be a worse regression than the one being fixed. The assertions read the
  `event` and `control` **fields**, not the sentence, since that is what an alert binds to; a test
  that read the prose would keep passing after a change that left every rule matching nothing.
  Also the **log line's two contracts** (`test_structured_logging.py`): it must be readable by a
  machine (one JSON object, one physical line, whatever a caller put in it) and *not writable* by
  a caller (a newline cannot forge a line, a `|` cannot forge a field, an ANSI escape stays inside
  its value). Plus the subtlety the design exists around — a fact learned in a CHILD task reaches
  the parent, because `BaseHTTPMiddleware` runs the endpoint in one and per-field `ContextVar`s
  would silently lose the actor. The **redaction** contract for logs and Sentry is
  `test_log_redaction.py`: every credential shape the codebase produces is scrubbed as a named
  field and loose inside a sentence, and the correlation ids — `trace_id` is 32 hex characters,
  exactly what the digest pattern looks for — survive.
  Also the **per-tenant resource bounds** (`test_tenant_resource_bounds.py`): the three refusals,
  and — the part that matters more — the legitimate uses each bound must *not* break. A workspace
  at its cap re-uploading its own catalogue still succeeds, because the bound counts what a batch
  ADDS rather than what it touches; a bound that refuses that gets removed within the week.
  Also the **startup hardening** (`test_config_hardening.py`): a deployed environment refuses to
  start with a placeholder secret, a short JWT key, `DEBUG=true`, `WB_FAKE_HARVEST=true`, CORS
  enabled, or a refresh cookie that would travel without `Secure`.
  Also **the diagnostic gate** (`test_diagnostic_gate.py`): the session `scripts/diagnose.py`
  hands a probe is read-only and pinned to one workspace, and offers no way to name another.
* `monitoring/` — the bounds on what one request may ASK for (`test_request_bounds.py`): the
  matrix working copy is a request body whose every cell the server recomputes, so its day list
  is capped at the widest window `resolve_window` would resolve — one constant, asserted to be
  the same on both sides, because a body cap below the window ceiling would reject a window the
  API had just allowed.
* `integrations/` — the WB retry policy: retriable vs fail-fast statuses, backoff and its cap,
  both `Retry-After` forms, WB's `X-Ratelimit-Retry`, penalty-block fail-fast, empty-200-as-no-data.
  Also the analytics **rate pacing** (`test_wb_rate_pacing.py`): the gate is consulted before
  *every* attempt including retries (a retry re-entering an empty bucket stalls on WB's 30 s
  socket hold, not a clean 429), WB's `x-ratelimit-remaining` is fed back even off a failed 500,
  a missing/garbage header teaches nothing, the queue cap refuses rather than parks a worker, and
  a Redis outage degrades to per-process spacing (fail-open).
  It also pins the PENALTY path: a 429 whose demanded wait exceeds the client's ceiling hands
  that wait to the gate rather than only logging it, an ordinary `Retry-After` short enough to
  sleep off does not block the bucket, and a penalised endpoint keeps refusing past its own
  refill. The Redis half of that — a block outlasting several refills, a lifted block returning
  the whole window, and the key outliving the block it records — is in
  `integration/integrations/test_wb_rate_gate_shared_budget.py`, because the ordering lives in
  Lua and a fake would only prove the fake. `unit/finreports/test_settlement_streaming.py` pins
  the walk's own gate: it withholds the budget header from the shared bucket and forwards a
  penalty block to it, which is the asymmetry that let the walk collect 429s and teach nothing.
  `test_marketplace_client.py` pins the FBS surface's two departures from every other WB endpoint
  we speak to: `/api/v3/warehouses` answers with a **bare array** (an envelope is rejected loudly
  rather than read as "this seller runs no FBS"), and the stocks read **omits** barcodes it does
  not know, so absent stays absent instead of being padded to zero.
* `users/` — invite gating, email canonicalization, duplicate/race conflicts, login timing safety,
  refresh rotation and family linkage, absolute session lifetime, logout idempotence.
  Also the **per-account login backoff** (`test_login_backoff.py`): the schedule, the cap, the
  reset, per-account isolation, fail-open on a Redis outage, and a corrupt stored penalty
  decaying to zero rather than to a hard block. Plus the property that makes the address safe to
  key on — it is `sha256(email)`, never the address, because Redis persists into an AOF volume the
  backups include and a plaintext key would make that volume a customer list.
  The service-level half lives in `test_login_and_rotation.py`: a backed-off account is refused
  **with the right password**, and the refusal is byte-identical to a wrong one — the backoff must
  not become the oracle the generic message exists to avoid.
  Also **password quality** (`test_password_breach_check.py`), driven against a stubbed httpx
  transport: a listed password found, an unlisted one allowed, padding rows not mistaken for hits,
  every failure mode (500, 429, malformed body, timeout, switched off) resolving to *allow*, and
  the k-anonymity bound itself — only five characters of the SHA-1 may leave, asserted by checking
  the other 35 and the password appear nowhere in the request.
  Also **account recovery** (`test_account_recovery.py`): single-use, short-TTL, hashed-at-rest
  codes, the attempt cap that makes six digits safe, and the uniform answer that keeps the request
  endpoint from disclosing whether an address is registered.
* `workspaces/` — lifecycle, encrypt-on-write, partial token updates, per-surface token resolution
  and the content→analytics fallback. The marketplace surface deliberately has **no** fallback:
  every other WB scope answers it 401, so a substitute would turn a skipped source into a failed one.
* `monitoring/` — the metrics matrix (build, edit reverse-solver, overrides, associative
  breakdown, and the «CPC» traffic group — `test_matrix_cpc_group.py` pins that a pay-per-click
  campaign is classified by its `payment_type`, not its bid type, that «Доля трафика» (traffic
  share) still sums to 100% within each traffic type, and that the delivery floor is read in the
  campaign's own billing model — a CPC campaign buys the same impressions for a fraction of the
  money, so a CPM-calibrated floor would cut real days), per-day notes and «Действия» (Actions),
  pinned SKUs, price and sale ingestion. Plus the two harvest-pacing behaviours behind
  «Обновить» (Refresh): the funnel and stocks analytics calls are fetched **in turn, never
  concurrently** (`test_harvest_analytics_pacing.py` — one in flight at a time, one failing does
  not cancel the other), and a cohort pass WB served **zero** days *raises* instead of logging a
  quiet "0 refreshed" (`test_cohort_pass_reports_silence.py`).
  Two files own what a harvest is allowed to give up on, both written from incidents where a
  harvest reported success and persisted nothing. `test_harvest_campaign_scope.py` pins the
  fullstats scope as a UNION of the still-running campaigns and those already holding rows in the
  window — WB reports a campaign's status as of *now*, so scoping by status alone silently drops
  the day a campaign was completed on, and that day's spend is uncollectable afterwards — while
  still keeping completed-and-quiet and foreign-SKU campaigns out, which is what keeps «Обновить»
  fast. `test_discovery_catalogue_fallback.py` pins discovery as a *source* rather than a
  precondition: a Content API that 403s (or a workspace with no token for it) falls back to the
  SKUs already on file, and only an empty catalogue is fatal. Both pin `wb_fake_harvest=False`
  explicitly — the fake path never calls WB, so leaving the flag ambient makes the result depend
  on test order.
  `test_fbs_stock_rows.py` pins the FBS→FBO seam: seller-warehouse stock arrives barcode-addressed
  from a separate WB surface and is filed under the CONFIGURED label (not WB's editable warehouse
  name, which is a primary-key column), with the size identity resolved from our own catalogue,
  in-transit columns a true zero, and an uncatalogued barcode dropped rather than guessed onto
  some other SKU.
  «Поиск по кластерам» (search by cluster, the block at the bottom of a SKU's page) owns two
  files. `test_cluster_ingestion.py` pins that the cluster TEXT survives ingestion at all (the
  zone aggregate sums it away, and nothing else records the seller's own search phrases), that a
  phrase repeated inside one day is summed rather than overwritten through its composite key, and
  that the average position is weighted by impressions with positionless rows excluded from both
  sides — a flat mean invents a ranking the ads never held. `test_cluster_search_service.py` pins
  the zero-filled day series, the phrase rules, and the probe's split answer: the page's own SKU
  is the rank, its siblings are context from the same scan, and one scan is asked for the whole
  catalogue because WB throttles the endpoint per IP.
* `monitoring/test_review_history_rules.py` — the review history's rules: an arrival is state
  and not an event, a rescore/replacement/return is; a FIRST storefront read of a merged card
  group records exclusions without dating them (dating them would invent a moderation on the day
  we happened to look); and a walk's missing reviews are believed only up to a floor or a share of
  the live ones — past that it is a truncated answer, not moderation.
  `test_review_history_schedule.py` keeps its beat entry in an hour no other entry starts in.
  `integrations/test_wb_feedbacks_client.py` pins that a non-envelope 200 raises rather than
  reading as an empty page (which would make every review «vanish»), and that every storefront
  read spends ONE bucket rather than one per `imtId`.
* `guide/` — the reference capture, which is the one module whose tests are its only guard:
  nothing in the app reads its rows, so a walk that silently stops working has no downstream
  symptom at all. `test_capture_windows.py` owns the resume arithmetic — the floor beating a stale
  watermark, and the inclusive 31-day window WB answers a wider one with a 400.
  `test_feed_walks.py` owns each feed's walk against a hand-written fake client, and the
  load-bearing case is the orders stream: a full 80 000-row page means more rows exist behind it,
  and a full page that fails to advance the cursor must stop rather than loop. It also owns the
  memory property — no batch is larger than the stream's batch size, whatever the page holds —
  and the cursor rule that follows from it: WB does not order a page by `lastChangeDate`, so a
  batch mid-page carries no resume point at all, and only the end of a page may name one.
  `test_source_catalogue.py` owns the catalogue's own invariants; the one worth knowing is that a
  source naming a token field the bundle does not have is NOT an error — it resolves to "" and
  skips silently forever, which is why it is asserted rather than reviewed.
* `finreports/` — the P&L composition, the harvest's refusal to overlap itself and its
  **observability**.
  `test_harvest_is_observable.py` pins the pair, not either counter: `HarvestProducingNoRows`
  joins rows against duration `on (harvest)`, so a harvest that records rows but never times
  itself has no right-hand series and the alert cannot fire for it at all. `finreports.finance`
  shipped in exactly that state.
  `test_harvest_freshness_gate.py` carries the asymmetry the gate is built on — which window to
  ask about, and what each answer from WB means. The only outcome that may skip the daily walk is
  WB answering *empty* over the days past everything harvested, so a never-harvested workspace and
  a probe that raised both harvest anyway: failing closed there would turn a single 429 into a
  silent gap, indistinguishable from a quiet week. It also pins WB's answer for an empty window:
  **204 No Content**, not `200 []`. And it pins that a wait of up to two refills is the next
  token's minute, while only a longer one is WB refusing.
  `test_settlement_watermark_prefix.py` owns the rule that keeps a part-walked week reachable:
  the walk certifies the **unbroken prefix** of windows it completed and nothing past the first
  one that stopped early. The load-bearing case is the third — a LATER window succeeding must
  not certify the gap before it, which is the shape that actually happened (the day that landed
  was the week's last) and the one a naive "max day I fetched something for" gets wrong.
  `test_harvest_single_flight.py` pins the last one: the finance walk is minutes of paced WB
  windows and the schedule ticks hourly, so a locked-out tick must open no session and make no WB
  call, and the «Обновить» button's read of that lock must **fail open** — reporting "running"
  because Redis is down would disable the manual escape hatch exactly when the scheduled path is
  also degraded. The lock primitive itself is pinned in `core/test_single_flight_lock.py`, where
  the two halves pull against each other and both are pinned: a LIVE holder keeps the lock past
  three TTLs (it heartbeats, so a long walk is never joined mid-flight) while a DEAD one lets go
  within one (an orphaned lock skips scheduled ticks). Plus: released on exception, never
  releases a lock it no longer owns, and a failed renewal never raises into the work it guards.
  One more thing worth knowing before touching that module: the **P&L closes without a
  tolerance**.
  `test_pnl_statement.py` pins the statement against the sums of one sample WB weekly report,
  because every way of getting this wrong yields a *plausible* statement rather than an error:
  refunds arrive positive and must be subtracted, the commission is a residual against the
  sale-side payout only, and the acquiring WB bills separately is a memo. Each of those was
  mutation-checked. `test_sku_report.py` pins the per-SKU cut («По артикулам», by SKU): a row's
  «к перечислению» (payout) is net of that SKU's own withholdings only, an uncosted SKU's profit
  is `None` (never "profit at free goods"), missing funnel/ad coverage is `None` not 0, and
  refund-only windows go negative instead of clamping. It also owns the one place WB's two
  advertising figures meet: the totals row returns the weekly «WB Продвижение» invoice before
  subtracting the burn, because the invoice is already inside «к перечислению» and the two are
  the same money.
  `test_stock_balance.py` pins «Баланс по товарным остаткам» (stock balance), where every mistake
  is again a plausible figure: a cell is units × cost price, an uncosted SKU keeps its units and
  reports `None` money (never "stock at zero cost") while counting into `uncosted_count`, a day WB
  never captured renders EMPTY rather than carrying the neighbouring snapshot, and a warehouse
  marked «Не считать» (exclude) ranks nothing. Note what it does NOT own: that response carries no
  totals at all. The grid's marks and its search apply without a round trip and each changes every
  total, so the panels are summed on the client (`useBalanceRows.spec.js`) — a server-side copy of
  the same addition would disagree with the screen the moment a mark was applied optimistically.
  `test_settlement_ingestion.py` owns the two silent-corruption modes of the ingest — a column
  missing from the upsert's `update_columns` survives a re-harvest with its stale value while the
  run still reports success, and the report period must come from WB rather than from
  `min/max(rr_dt)`. `test_wb_labels_are_pure_cyrillic.py` replaces what widening ruff's
  `allowed-confusables` gave up: a Latin lookalike inside a WB label we compare on would silently
  drop a whole operation. `test_settlement_streaming.py` owns the third such mode, which is not a
  column but a *shape*: the settlement walk must stream, and its first test asserts that by
  counting live `WBReportDetailRow` objects through `gc`, because an accumulator is invisible to
  every other kind of assertion and the last one cost an OOM kill mid-harvest. It also pins what
  streaming put at risk — a report straddling a page boundary keeping the period WB stated, and a
  mid-walk failure propagating rather than being swallowed into half a window.
  `test_settlement_reconciliation.py` owns the daily pass that exists because the freshness gate
  is structurally forward-only: it probes the day AFTER the watermark, and the watermark jumps to
  the newest report's stated end, so a report WB serves for earlier days would be unreachable for
  good. Both halves are pinned because either alone is inert — the span reaches back behind the
  watermark, and the pass runs even when the gate says «ничего новее нет» (nothing newer), which
  is true and beside the point exactly when a back-dated report is what is missing. Also pinned:
  the hourly tick still skips (or every hour becomes a walk), «Обновить» never widens into it (a
  click must not spend a fortnight of a seller's settlement budget), and it still queues behind
  the harvest lock. It is sized from an incident in which a back-dated report stayed unserved for
  days and then fell out of reach.
  `test_harvest_due.py` owns the **gate on scheduled ticks**: the calendar of what a day can bring
  (Sunday or month end for a weekly report, yesterday for a daily one) and the fleet asking WB only
  about the sellers still owed something; `test_task_wiring.py` pins that every scheduled tick is
  gated and the reconciliation never is.
  The same file owns the **ration**, which is a cost property rather than a logic one and was
  measured rather than reasoned about: a window costs a full WB refill of *waiting* (the requests
  themselves take seconds), and workspaces are walked in sequence, so a fleet-wide pass is a sum
  that grows with every seller. So one workspace per run, round-robin: flat in fleet size, every
  workspace inside one cycle, stable when the loader reshuffles its rows, and a warning once the
  cycle grows long enough that a workspace's turn could arrive after the lookback has passed the
  day it needed. Plus the priority rule: a workspace with a KNOWN gap jumps the rotation (oldest
  gap first, since it is nearest to ageing out of WB's reach), which is what lets the alert fire
  on a stuck gap rather than on one merely queued behind other sellers.
  Two files carry that gate's answer forward into the P&L's freshness line, which exists because
  a statement ending nine days ago is usually a quiet week and occasionally a dead harvester:
  `test_freshness_record.py` owns the recorded verdict — the fail-open rule stated once (only
  `up_to_date` and `wb_empty` stop a harvest), a 30-day TTL because an expired entry reads as
  "never checked" and a *stale* probe is the evidence that matters, and the degradation that
  matters most, an unreadable record becoming "we have not checked" rather than a half-parsed
  value. `test_harvest_records_freshness.py` owns the harvest loop's half: the verdict is recorded
  **before** the branch, so the quiet path leaves the same trace the harvesting path does; a
  completed walk then supersedes it, because the walk asks WB about the same days and a finished
  one is strictly better evidence (otherwise a page warns «данные могут быть неполными» — data
  may be incomplete — over a statement the walk has just proved complete); a walk that lost a
  window supersedes nothing, since upgrading an incomplete walk to «нового ничего нет» would
  report a gap as reassurance; and a Redis outage never reaches the walk it annotates.

`test_worker_memory_signal.py` owns the two signals the worker once had none of, when prefork
children were being OOM-killed and the only evidence anywhere was `dmesg`. The memory reading is
a cgroup collector rather than a gauge, because multiprocess mode drops `prometheus_client`'s
process collector and the worker has no exposition route to sample from — so the file also pins
the two series NAMES against the alert that divides one by the other, which `test_alert_rules.py`
structurally cannot see (a collector declares no metric object). And it pins that a task lost
with its worker is counted apart from one that raised: a handful of those a day is far below any
failure-rate threshold, so inside the general counter it is unreachable by any alert. It then
owns the two histograms that exist to CHOOSE the per-child memory limit rather than to alarm on
it: the water line a task leaves (taken from the same `billiard.compat.mem_rss` the recycler
compares, so the two cannot drift) and the growth that task caused, because a high-water mark is
inherited and the absolute figure alone blames whichever task ran after an expensive one. Last,
the sweep: a process that imports the app retires its own live-gauge files on exit and **only**
its own — the healthcheck was leaving two behind every 30 seconds against a small tmpfs, and the
test pins both halves of that, since a sweep that took another process's files would be the
worse bug. It also owns the floor a task starts from, written at `prerun` — the one memory reading
a task the kernel kills still leaves. The postrun pair is survivor-biased: killed tasks record
nothing, so without the floor the histograms understate exactly the tasks that matter.

The streamed reader's tests own one contract that is easy to miss: **what the real reader
produces must survive being stored.** ijson decodes every JSON number as a `Decimal` and `httpx`'s
`.json()` never did, so moving a feed onto the stream silently changed the type of every price in
a payload that goes straight into JSONB — and nothing in the unit tier could see it, because the
fake client the feed walks are tested against hands back plain dicts.
`test_wb_streaming_reader.py` now asserts `json.dumps` on what the capture client returns, and
asserts the opposite for the settlement client, whose callers validate into `Decimal` money
fields and must not go through a binary float on the way. The same file pins the streamed read's
retry ladder: a connection that fails to OPEN is an `IntegrationError` retried like any request,
and a penalty block past the client's `retry_after_ceiling` penalises the gate and fails at once
instead of being slept off inside the task. The integration tier pins the consequence: a row the
column will not take fails its own feed and not the whole cadence.

**`unit/core/`** also holds the two app-wide walkers that make an invariant impossible to forget
rather than merely documented: `test_every_covered_route_binds_a_tenant.py` (every route in a
policy-covered module resolves a workspace binder) and
`test_every_writing_route_is_guarded.py` (every mutating verb resolves a guard at least as strong
as `WritingAccess`). Both derive the route list from the running app and keep a reasoned
exemption list that is itself checked for staleness. Both prove a guard is *present*, never that
it is the right one — that stays with the `security` skill.

**`unit/ab_tests/`** — the photo rotation, whose load-bearing rules all fail silently rather than
loudly. `test_rotation.py` pins both triggers and, above all, their **exclusivity**: an
impressions test must ignore the clock and a time test must ignore the counter, because
"whichever comes first" would judge the photos on different exposures. `test_runner.py` pins the
order of one polling pass — close the window, move the baseline, decide, swap — which is what
lets a photo turn over several times a day without any interval being split between two
variants; it also pins that a failed WB upload leaves the pointer on the old photo, and that a
test's first poll seeds a baseline instead of crediting its first photo with everything the card
earned since midnight. `test_collection.py` owns the subtraction that turns WB's
cumulative-since-midnight counters into intervals: clamped at zero so a restated day cannot
rewind the rotation, split by day so midnight does not stall it. `test_triggers.py` owns the
configuration rule both the create schema and the settings PATCH call — one module precisely so
the two cannot drift into "create refuses a stray field, edit quietly accepts it".
`test_metrics.py` asserts the three chained conversions against WB's own «A/Б» result screen to
the second decimal, because each one divides by the previous stage and a wrong denominator still
lands in a believable 0–100 range. `test_status_transitions.py` owns the hand-set pause and
cancel: a pause only from running, a cancel only from running or paused, and nothing written on a
refusal — because a pause used to be accepted from «Завершён» (finished), and the launcher's own
guard then let the finished test start again.

`unit/summary/` owns the four decisions «Сводка» (Summary) makes that the per-SKU report does
not, each pinned by its own case and each verified to fail when the rule is removed: the margin is
withheld entirely while any settled SKU is uncosted (the report is softer, which is right for a
table and wrong for one headline); WB's weekly advertising invoice is swapped for the burn the
statistics recorded, so the daily margin does not crater on invoice days; the bonus is spread
across the window in proportion to spend rather than taken per day, which keeps every day
non-negative AND keeps the series summing to the window; and account-level money raises no
category bar. The builders live in `builders.py` because a hand-written P&L row carries thirty
fields and two files read them.

`unit/heatmap/` owns the rules a heatmap gets wrong while still looking right: a ratio's total is
re-derived from summed facts (a week's CTR is Σ clicks / Σ views, never the mean of seven CTRs);
stock is the LAST day's level across days and a sum across articles; a day the funnel never
reported is `None`, not zero, while a reported day with no ad row is a real zero; profit is
withheld the moment one article in a cell has no cost price, and subtracts advertising only for
the settled days; «Итого» (total) folds DISTINCT articles, so one article in two groups is counted
once; weeks run Monday to Sunday, clipped to the window. The colour rule is pinned in the
frontend's `heatScale.spec.js` / `grid.spec.js`: the median as the norm, a hand-set norm in its
place, and a summed metric compared with a daily norm per day of the column.

`unit/advertising/` owns the money rules of «Реклама» (Advertising): which zone a campaign-day's
spend lands in (the matrix's `_classify` restated for money — a manual search campaign's
remainder is the catalogue unless its search slice is missing, CPC is its own group, a slice
above the total is clamped); how WB's batched bonus is placed on days (its own day first, then
the days before it, then after, never above a day's spend); that the headline, the days, the
zones and the articles are four cuts summing to one total, with DRR's numerator stopping at the
last settled day; and each article's money by zone — its part of every campaign-day split by that
day's zones, summing to the article's row to the kopeck. The frontend's `zoneModel.spec.js` /
`skuModel.spec.js` pin the cards, an article's zone lines and a group's zones and DRR re-derived
from summed money; `AdsSkuTable.spec.js` the ▶ opening a row into its zones, and
`AdsDailyChart.spec.js` the legend switching a line (and the DRR axis with it) off and on.

**The alert path.** `test_alert_path_probe.py` owns the question behind `/healthz/alerts`: only
an *active* `Watchdog` in Alertmanager's answer reads as "ok" — a suppressed one, another alert,
an error page, junk JSON or an unreachable Alertmanager all read as down without raising — and a
flood reaches Alertmanager once per cache window. `test_telegram_relay_wiring.py` pins the alert
relay's agreements across its config files (relay port = `api_url` port, the Prometheus target =
the metrics bind, `Watchdog` reads the relay's real backend name) and its two security
properties: no listener on a wildcard address, and no route that leaves Telegram's address space.
The route itself (200 `alerts-ok` / 503 `alerts-down`, nothing about the failure in the body, kept
out of the request log) is in `component/test_health_and_metrics.py`; the rendered Alertmanager
config (Watchdog first, to a receiver with nothing in it) in
`integration/core/test_alertmanager_config.py`. **Deliberate gap:** nothing in CI dials Telegram
through the relay.

### `component/` — the real app, persistence faked

Owns the wiring: route paths and verbs, the DI graph resolving, auth/tenancy/role guards, request
validation and response shaping, cookies, and domain error → HTTP status mapping. Per module:

* `summary` — the workspace header scoping the read, and the window being bounded *before* any
  aggregation runs (a multi-year window over the whole settlement table is a denial of service
  with a valid token attached); refused without its own page grant even to a holder of
  «Мониторинг» and P&L, and opened by that grant alone.
* `heatmap` — the same window bound (366 days inclusive), its closed metric list, the bound on
  the article filter, a paying customer let in and a lapsed one refused, group and norm writes
  refused to a read-only manager, a group of another workspace answered 404, the page refused
  without its own «Тепловая карта» (Heatmap) grant and every metric — money included — opened by
  that grant alone. In `test_heatmap_group_routes.py` the groups and their card catalogue are
  opened by any one page that carries the filter (`GROUP_MODULES`: «Сводка», P&L, «Тепловая
  карта», «Реклама») and by none of the others; in `test_heatmap_norm_routes.py` the hand-set
  norms are refused without the heatmap grant and their metric, article and value are bounded.
* `advertising` — a paying customer let in, the page refused without its own «Реклама» grant and
  opened by that grant alone (neither «Мониторинг» nor P&L is asked for, by the owner's decision),
  the header scoping the read, a window over the cap or inverted refused without echoing the dates.
* `workspaces` — the `dev` role gate on admin routes and tokens never appearing in a response;
  and in `test_workspace_settings.py` the workspace's «Промо-бонусы» (promo bonuses) switch: saved
  by a writer and listed back, refused to a read-only manager, 404 in another company's workspace,
  an empty or unknown body 422 (the frontend's `workspaceSettings.spec.js` pins the switch
  reverting when the save fails).
* `monitoring` — workspace scoping, paging bounds, SKU ownership on read *and* write, and
  `/skus/lookup` not being swallowed by `/skus/{nm_id}`; the two per-SKU «Поиск по кластерам»
  routes — both behind the ownership guard, a phrase required on the live probe, the workspace
  header reaching the probe (the scan looks for the whole catalogue), and a throttled WB arriving
  as **502** rather than as an empty ranking (`test_cluster_routes.py`).
* `finreports` — the cost-price editor's boundaries — a negative or five-digit-slip cost, one `nm_id` twice in a batch, and tenancy on
  the **write** path, since a cost price is the seller's own commercial data; the per-SKU report
  route: an arbitrary date window passes through verbatim, and the monitoring figures reach the
  service through the router's contract calls, monkeypatched at the router; and the balance route, which picks a DAY rather than a window —
  an omitted one falls back to the newest snapshot on record (never "today", which usually has
  none yet), the stock and catalogue names arrive through the monitoring contract, and a mark of
  an unknown `kind` is a 422 rather than a row nothing can ever match — including the two RETIRED
  «Закрепить» (pin) kinds (`sku`, `warehouse`), the case that matters being a browser tab left
  open across a release still sending them. And the «Обновить» trigger, where the assertion is a
  negative — a click while a harvest is in flight enqueues **nothing at all**
  (`test_harvest_routes.py`), so an impatient seller cannot pile a run per click behind a long
  walk. An unknown `grouping` on the P&L is a 422 rather than a silent fallback to weekly:
  answering a different question than the one asked is worse than an error on a financial
  statement.
* `users` — the full auth surface plus the shared access-token guard across all routers.
* At the tier root, the **request log's bindings** (`test_request_logging.py`), which the unit
  tier cannot reach: that the middleware runs at all, that a real signed token makes the line name
  the account, that `X-Request-Id` comes back on the response (the whole practical value of a
  request id — "it failed around two" is not a search), that the liveness probe stays out of the
  log, and that no context survives the request into the next caller's lines. An abandoned GET is
  cancelled and answered 499 while a finished one, a write, and work after the last byte are left
  alone (`unit/core/test_cancel_on_disconnect.py`; that the cancellation reaches PostgreSQL is
  `integration/core/test_abandoned_read_stops_in_postgres.py`).

`monitoring/test_refresh_bounds.py` covers the two controls on «Обновить», which do different
jobs: deduplication answers an identical in-flight request with that task's id (impatience costs
nothing), while the budget is the bound on abuse and is keyed on the **workspace** — keying it on
the address would hand one tenant a fresh allowance per device and make two colleagues behind one
office NAT share one. Both stores are the real ones, backed by the tier's in-memory Redis, so the
key each writes is under test rather than stubbed. `finreports/test_harvest_routes.py` pins the
matching property for the finance button: it enqueues a walk scoped to the caller's own workspace,
not the fleet. It also owns the rule that **every click answers and none of them waits** — a click
while the finance bucket is shut is refused with the wait attached and enqueues nothing (a queued
run would only sit still until the bucket refilled), while a run already in flight is reported
ahead of that rate limit, since the running walk is usually what emptied the bucket and «уже
идёт» (already running) is the more useful half of the pair. The same file owns the freshness
half of `GET /harvest`: the report we hold and the last recorded verdict travel together (either
alone is unreadable), a failed probe reaches the page as `probe_failed` rather than as an empty
answer, and nothing recorded arrives as `null`.

`test_error_disclosure.py` pins that a 5xx answers with its class's `client_message` and never
the message the raise site wrote — asserted against the whole response body, since the point is
that the detail does not reach the client by any route through the envelope. Two of its cases
guard the other direction: a 4xx must keep its own message (blanket-replacing every one would
turn every actionable error into «что-то пошло не так», "something went wrong"), and the rule
keys on the status rather than a per-class allowlist, so a server error added later inherits it.

`test_documentation_exposure.py` sits at the tier root because it is about the app itself
rather than a module: the three documentation URLs move as one (hiding the viewers while still
serving the schema withholds nothing), `None` unmounts the route rather than hiding it, and the
running app takes them from the setting. That last assertion only bites in a deployed
environment — the suite runs as `local` — which is a known limit of the tier rather than
something to paper over.

`users/test_auth_rate_limit_spoofing.py` is the one place this tier wraps the app in uvicorn's
own `ProxyHeadersMiddleware`, configured with the deployed `--forwarded-allow-ips "*"`. Speaking
ASGI directly, the tier picks the client address itself, so a spoofing test without that wrapper
would pass against the very bug it exists to catch. It pins that a forged `X-Forwarded-For`
neither escapes a spent auth budget nor opens a counter of its own — and, incidentally, that
uvicorn still resolves the chain the way we assume (those semantics changed once already, in
0.30).

`ab_tests/` covers the routes' own wiring: workspace scoping, a foreign test reading as 404 rather
than 403, the multipart upload arriving with its bytes and MIME type intact, and the domain's
refusals (a full rotation, deleting the live photo) surfacing as 409.
`test_ab_test_creation.py` is the configuration half — that sending the other trigger's setting
is a 422 rather than a silently dropped field, in both directions, on create *and* on the
settings PATCH, and that the PATCH needs no WB token because it never touches the card.

A component test that reaches the database fails loudly (`_TripwireSession`).

### `integration/` — real Postgres and Redis

* `ab_tests/` — `test_ab_test_creation_row.py` pins that creating a test returns a row at all:
  the shared projection reads `len(test.variants)`, and on a just-inserted instance that is a
  lazy load, which on an async session raises `MissingGreenlet` and answers 500. Nothing below
  this tier could see it — the component tier stubs the service. Also the search predicate the
  one list box depends on, matched field by field (name, the seller's article code, a *fragment*
  of the bigint nmID, status) plus the tenancy guard inside it; the idempotent window insert,
  which is what stops a retried polling pass from counting the same five minutes twice; the
  snapshot round-trip that is the poller's entire memory between passes; and the append-at-the-end
  position of a new photo.
* `monitoring/test_review_history.py` — the review history over two days against real SQL:
  a review missing from a COMPLETE walk is vanished that day and no other workspace's row moves, a
  walk that failed part-way declares nothing, a mass disappearance is refused, the overlap
  between pages keeps the review that slides across a boundary when another is answered
  mid-walk (it fails with the overlap at 0), one rating snapshot per day, and the storefront is
  left alone after three refusals in a row.
* `guide/` — `test_capture_is_incremental.py`, the transaction half of the batched capture.
  The walks yield and `capture` writes as they go, so rows reach the database before the run
  ends and the watermark can disagree with them. Both directions are pinned, because only one
  of them is recoverable: rows stored past the watermark are merely re-read next run, while a
  watermark past unstored rows skips them for ever and nothing downstream can tell. A walk that
  dies keeps every batch it stored, and its cursor stops at the last batch that named a safe
  one. Real Postgres because the subject is what survives a commit.
* `users/` — the **session-revocation lever** (`test_session_revocation_lever.py`): ending
  every session of one account revokes each family's rows AND stamps the Redis watermark, which
  is the half that makes it immediate rather than a fifteen-minute sign-out. Real Redis, because
  a fake would agree with either answer. Refresh rotation against real rows: breach detection
  (`test_breach_detection.py`, run with the replay-grace window **disabled**, so it keeps pinning
  that a token replayed after the window still kills the lineage) and the concurrent-tab race the
  window exists for (`test_concurrent_tab_refresh.py`). The latter is here and not lower because
  its subject is which rows survive and which token is live — and because the grace store is
  Redis. It covers both collisions: tabs far enough apart to find the token used, and tabs
  together enough that the conditional `UPDATE` decides between them.
  `test_every_tab_converges_on_one_live_token` is the one that forbids the easier design, where
  each racing tab gets its own sibling and the family quietly gains several live leaves.
  Breach detection also pins that the revocation **survives the failing request's rollback** and
  is scoped to the replaying **family only**, so an unrelated device stays logged in — which is
  why a replay revokes a lineage and not the account.
  Also **what logout actually ends** (`test_logout_ends_the_access_token.py`). The gap it closes
  lives *between* what the service writes to Redis and what the request path reads on the next
  call, so a test of either half alone passed throughout. Four cases through the real app: the
  access token dies the moment you log out; logging out one browser leaves the other signed in
  (which is why the watermark is per-family and never per-user); "log out everywhere" is still
  wide; and a detected refresh replay ends its lineage's access tokens too.
* `organizations/` — the **single-use credentials**, raced. Activation codes and invitations
  are both claimed by a conditional `UPDATE`, and both have a test that runs two redemptions
  concurrently on their OWN connections — the sequential cases pass against a check-then-write,
  because the first has committed by the time the second looks. Neither uses `db_session`: that
  fixture's rolled-back transaction makes one connection's writes invisible to another, so the
  race could not occur.
* `organizations/` — the **audit log**, in halves that need different evidence.
  `test_audit_log_is_append_only.py` goes *around* the ORM and issues the SQL directly, because a
  test of the repository would only prove the repository has no `update` method, which nobody
  doubted: `UPDATE`, `DELETE` and `TRUNCATE` are all refused by the database, and the absence of
  foreign keys on the actor and tenant is pinned so that adding one later looks like the
  regression it would be. `test_audit_events_are_recorded.py` drives the real routes: the actor,
  tenant and target land; the invitation token does **not**; and a 404 records nothing, because a
  log that reports attempts as successes is worse than no log. It also covers **reading the
  trail back**: an owner sees their own organisation's entries, another organisation's are
  invisible (verified to fail when the loader's `WHERE` is removed, so it is not passing on the
  fixture's shape), a token issued moments earlier does not come back through the endpoint, and
  the page size is bounded because this is the one table that only ever grows.
  `test_subscription_change_trail.py` is the third half: a **trigger** on
  `organizations.subscriptions` writes `SUBSCRIPTION_CHANGED` for every UPDATE and DELETE, so a
  renewal done as raw SQL is recorded too (unattributed, `source = 'sql'`) — the tests issue that
  SQL directly, the way a manual renewal would be done. The renewal rule itself (continue from
  the old end while still open, from now once closed) is unit-tested in
  `unit/organizations/test_renewal_rule.py`.
  `test_page_grants_migration.py` replays `d7f1a3c95e24` on a scratch database: «Сводка» is
  written only where «Мониторинг» AND P&L were held and «Тепловая карта» where «Мониторинг» was,
  on memberships and invitations alike — so a manager whose owner closed P&L does not wake up
  to the workspace's revenue — plus the six-page column default and a clean downgrade. The guard
  rule itself ("any of" for the groups, an empty set refused when built) is
  `unit/organizations/test_module_guards.py`.
* `core/` — **the demo seed's guard** (`test_demo_seed.py`): it refuses a database holding an
  account or a catalogue card that is not the demo's — it empties every table before writing —
  and lets a freshly migrated one through. The same file seeds the shop and builds the newest
  week's P&L through the real service and loaders: every article sold and costed, no «unknown»
  caveat, which is what the demo exists to show.
* `core/` — the **least-privilege database role** (`test_least_privilege_role.py`). A SQL file
  nobody executes is a plan, so this one reads the shipped script, applies it to a real
  PostgreSQL and then *connects as the role it creates*. The interesting assertions are the
  refusals — no `DROP TABLE`, no `CREATE TABLE`, no `DISABLE TRIGGER`, no `UPDATE` on the audit
  log, and not a superuser, which would silently bypass every other assertion. The audit-log case
  additionally asserts *which layer* refused: the message must be the grant's ("permission
  denied") and **not** the trigger's ("append-only"), because a missing second layer would
  otherwise pass as a present one. Its unit-tier neighbours are
  `test_sql_scripts_do_not_log_passwords.py`, which reads every operator script for an
  `ALTER ROLE … PASSWORD` not wrapped in `log_statement = 'none'`, and
  `test_only_the_api_uses_the_restricted_role.py`, which keeps migrations, workers and the
  backup on the owner.
  Also **tenancy enforced by the database** (`test_row_level_security.py`), which is the same
  trick applied to a different guarantee: it installs the role AND the policies, then runs a
  `SELECT` with **no tenant predicate at all** and asserts it sees one workspace. The queries
  there are deliberately naive — a test that scoped its own SQL would pass with the policies
  dropped, which is the one thing it must not do. Also: the other tenant's row stays invisible
  when asked for by id, a write into another workspace is refused (`WITH CHECK`, the direction
  people forget), a query with nothing bound **raises** rather than returning zero rows, and
  the owner still crosses workspaces — pinned as intended, because that is what keeps
  migrations and the nightly harvests working. One case compares the script's table list
  against what PostgreSQL actually enforces, since a typo in a schema-qualified name would
  otherwise leave a table looking covered in review and open in fact. One case runs a real
  application function under the policies instead of a hand-written query: saving a WB token
  seeds the workspace's backfill lanes through `start_backfill`, which opens a session of its
  own and so has to bind the tenant itself — and since that function swallows every exception
  by design, the only observable failure is lanes that never appear. Two further cases cover
  the *binder* rather than the policies: the cases above call `set_config` directly, so
  without them `set_workspace_context` — the function the application actually uses, and its
  "do nothing unless the policies are installed" gate — would never be exercised at all.
  `test_diagnostic_gate_is_enforced.py` is the same idea for `scripts/diagnose.py`: a probe run
  through the gate cannot write and cannot see a second workspace.
  Also rate limiting against real Redis (per-IP budgets, scopes, TTL, fail-open); the
  session-revocation watermark; the request unit of work including **cleanup under task
  cancellation**, asserted against `pg_stat_activity`; Alembic integrity (single head, clean
  replay, no model drift, no `public` tables).
  **The backup's dump retry** (`test_backup_dump_retry.py`) sits here because it runs the real
  `create_dump` from `scripts/backup/lib/dump.sh` in bash with `pg_client` stubbed. Pinned: one
  lost connection costs a retry and a warning, not the night's backup; a server that stays down
  still fails the run with the alert, after exactly the configured attempts.
  **Bulk writes leave the connection as they found it** (`test_bulk_upsert_memory.py`): three
  batch sizes of the 63-column settlement detail through the real `bulk_upsert`, measured as the
  backend's own `RssAnon` via `pg_read_file('/proc/self/status')` — the figure the kernel's OOM
  report names. The multi-row `VALUES` form left tens of megabytes behind (asyncpg caches every
  statement it prepares, and each batch size was a new one); `src/core/upsert.py` keeps it small.
  The unit half (`unit/core/test_upsert_rows.py`) pins that rows with different keys are refused,
  because `executemany` would otherwise drop a key the first row lacks from every row, silently.
  **The crash-recovery signal** (`test_postgres_crash_signal.py`): the scrape publishes
  `pg_stat_bgwriter.stats_reset`, which PostgreSQL moves only when it discards statistics after a
  crash — the one trace of a two-second recovery that outlasts a 15 s scrape. The unit half pins
  that an unreachable database leaves the last value and does not raise.
* `workspaces/` — ciphertext in the column read via raw SQL; rotation replacing rather than
  duplicating; the FK cascade leaving no orphaned credentials.
* `monitoring/` — the tenancy predicate treating foreign, unregistered and nonexistent SKUs
  identically; vendor-code search; the day-header carry upsert (seeds, never overwrites).
  `test_export_loaders_are_scoped.py` owns every cross-module loader on the monitoring
  contract, and its count guard is the deliberate step that says a new one was reviewed for
  tenancy (a leak in `load_card_photos`, say, is not a wrong number but another seller's product
  photo beside your own article).
* `integrations/` — the prices and statistics clients end to end over a mock transport; and the
  WB rate gate against **real Redis and its real Lua** (`test_wb_rate_gate_shared_budget.py`) —
  the part the unit tier cannot prove: the bucket is shared across *processes* (two gate instances
  = two Celery workers on one token), separate per endpoint and per token, honours WB's
  `remaining` header, and refuses past the queue cap. This is the guarantee that a nightly cohort
  pass and an interactive «Обновить» queue against one budget instead of racing it into 500s.
  Three cases belong to the tier for the same reason the others do — they are arithmetic inside
  the Lua, and a fake would prove the fake. A block is served **longer** than WB demanded; a
  refusal arriving with no block of ours standing **doubles** the last one; a block already
  standing is never shortened. Together they encode an observed escalation: WB's
  `X-Ratelimit-Retry` is the remainder of a window it may extend, and serving exactly that number
  is what puts the next probe back inside it. The same file pins the **peek**: a second Lua script
  over the same bucket that must agree with `acquire` while writing nothing to it. It is pinned as
  read-only (the P&L page may ask on every load, and a peek that spent a token would drain the
  budget the settlement walk is metered against), as reporting WB's own stated block rather than
  our refill estimate, and as crossing processes — the API answers the click, the worker spends
  the budget.
* `monitoring/` — `test_fbs_label_rename.py`: an FBS warehouse label is a primary-key value, so
  renaming one (`c7e4a1d90b62`) has to carry its stock snapshots and «Отгрузить» (ship) marks with
  it — including the row a previous migration seeded — and leave the FBO warehouses filed in the
  same table untouched. It still asserts on the marks after that feature was removed, and should:
  the test replays history up to `c7e4a1d90b62`, where the table still exists, and what it pins is
  that MIGRATION, which is immutable.
  `test_stock_sweep_scoping.py`: the daily stock sweep can spare named warehouses. FBO and FBS
  reach one table from two WB surfaces that fail independently, so an unscoped sweep after a
  failed FBS read would report a full seller warehouse as emptied overnight.
  `test_cluster_search_sql.py`: everything in the «Поиск по кластерам» reads that IS the SQL — the
  per-SKU predicate repeated in both statements (two SKUs routinely share a cluster, and the block
  must not report the account's traffic as one card's), the window bound, ranking by impressions,
  the impression-weighted position `CASE`, the four-column upsert making a re-harvest idempotent,
  and the sweep clearing only the named campaigns.
* `finreports/` — `test_pnl_reconciles.py`, which owns the **aggregation** rather than the arithmetic. Twenty-eight
  `SUM(CASE …)` expressions over one table have to partition it into disjoint buckets, and a single
  mis-scoped `CASE` double-counts a charge while the statement still looks like a statement. It
  pins that the blocks close in `numeric`, that the buckets sum to the total under every grouping,
  that a foreign workspace's settlements are invisible, and — the one assertion that catches a
  widened row set — that the **residual commission equals the one WB published**
  (`ppvz_vw + ppvz_vw_nds`). `test_pnl_caveats.py` owns the other half: what the statement admits
  it cannot verify. Cost coverage and the wrong-currency drop, an unrecognised operation, a window
  still mid-backfill, a bucket covering only part of a WB report, and the «в т.ч. НДС» (of which
  VAT) sub-line being summed over the rows the line above it is.
  `test_harvest_is_atomic.py` runs the real `harvest_workspace` against real PostgreSQL with fake
  WB, and owns the per-batch commit rule: a request that dies mid-page leaves none of its own
  uncommitted rows, the batches already committed and the requests before it stand, and the
  report is still called short — its header is booked last, so a half-written report never reads
  as held. It also pins the shortened retry ladder for the client inside a transaction.
  `test_wb_report_totals.py` owns what the header is allowed to claim against WB's own list:
  WB's totals land only on a report we hold and only for its tenant; a report short of its own
  rows stops counting as held (a restatement inside the tolerance does not); a report WB lists
  money in is never booked over zero rows, while one that owes nothing may be; and
  `reconcile_against_wb` reports zero for a report that adds up and the gap for one that does
  not. `test_pnl_reconciles.py::test_a_correction_takes_its_sign_from_the_document_type` pins
  the payout sign rule — «Возврат» (return) by `doc_type_name` subtracts, anything else adds —
  which is what reconciles every report to WB's own `forPaySum`.
  `test_sku_identity.py` owns what NAMES a SKU on the balance grid: the article, subject and brand
  come off that SKU's **newest** settlement row, per tenant, rather than an aggregate over its
  history — an aggregate hands a renamed card whichever of its names sorts highest, and it also
  reads the whole settlement table to do it, which is what sent the query to a per-SKU LATERAL.
  A SKU that never settled stays ABSENT rather than triple-empty, because absence is what makes
  the caller fall back to the catalogue vendor code.
  The shared fixture in that directory's `conftest.py` is load-bearing in one non-obvious way: its
  «Возмещение издержек» (expense reimbursement) row republishes its charge across
  `ppvz_vw`/`ppvz_vw_nds`, as the real rows do. Without that the two commission tests would pass
  on a basis that drifts over a long history. `test_sku_report_reconciles.py` owns the per-SKU
  partition: Σ SKU rows + the «Без привязки к артикулу» (not tied to a SKU) bucket equals the
  window totals with no tolerance, account-level charges never smear across SKUs, and the
  monitoring contract loaders (orders from the funnel, ad spend from the Promotion API) deliver
  per-SKU figures — or `None`-with-a-caveat when their history does not cover the window.
  `test_settlement_watermark.py` owns the separation a lost report turned on: a report header
  claiming a later period must NOT move the walk's watermark (the two figures come from different
  places and are allowed to disagree), and the watermark never rewinds — two harvests can overlap,
  and the loser must not re-open a window already closed.
  `test_freshest_report_is_selectable.py` owns a relationship rather than a value: the day
  `latest_settled_date` reports — `max(date_to)`, what «Обновить» announces — must be a day
  `list_periods` actually reaches, since the SPA's period picker is built from the latter. They
  were computed by two queries with different filters, so a report WB stated an end but no start
  for was announced and then unselectable, and the freshness gate (which probes the days *after*
  `latest_settled`) never asked for it again. Both queries are SQL, which is why this is here and
  not a tier down.
  `test_settlement_gap_detection.py` owns the detector for a missing settlement day, and its whole
  design is in one assertion: **a quiet seller with no rows is not a gap.** Keying on missing rows
  would alert on every small account every night until somebody muted it, so the signal is a day
  covered by no report PERIOD, WB's periods being what tiles the calendar. Also pinned: the
  original shape (two consecutive weeks on file and a single day between them in neither), a
  half-known period covering the day it does know rather than inventing a hole beside it, the
  cutoff that keeps unreachable history from becoming a nightly alarm nobody can act on, and a
  neighbour's complete history never filling this tenant's hole. Real Postgres because
  `generate_series` over a date range with `coalesce` on both endpoints is database behaviour,
  not Python.
  `test_latest_report_header.py` owns the ordering behind the freshness line's first half — the
  newest report is the one covering the latest *settlement period*, never the one harvested most
  recently (a backfill would otherwise label an old week as the newest thing WB published), and a
  header WB stated no period for sorts **last** rather than first, which is what `NULLS LAST` buys
  and what makes this a real-Postgres test rather than a unit one.
* `heatmap/` — `test_heatmap_sources_are_scoped.py` seeds two workspaces with facts on the same
  day and proves every per-SKU-day loader (funnel, ads, prices, stock) and the catalogue answer
  for one; that the `nm_ids` narrowing cannot widen the scope; that a group cannot hold another
  workspace's article; and the grid end to end — totals, the category filter, the cut by group.
  `test_heatmap_norms.py` proves the hand-set norm's upsert (a second set replaces), that a norm
  cannot be set on another workspace's article, and that a list or clear reaches one workspace
  only. `finreports/test_sku_days_reconcile.py` proves the settlement's per-SKU-day cut adds up to
  the per-SKU window row exactly — revenue, units and payout — so the heatmap and «По артикулам»
  cannot disagree about one article's money.
* `monitoring/test_ad_campaign_facts_are_scoped.py` — the advertising page's campaign-grain
  loader: another workspace's spend, search slice, campaign settings and bonus never reach it, and
  a campaign that also advertised a foreign card hands over only its share of the bonus.
* `summary/` — `test_summary_reconciles.py` shares the finreports miniature week and proves the
  two pieces of new SQL: the **day** cut of the settlement partitions the same rows the window
  total does (Σ days = the revenue card, no tolerance), and the whole-workspace daily loaders go
  through the `product_card` semijoin, so a neighbouring tenant's funnel never reaches this
  chart — neither monitoring table carries a workspace of its own. It also proves the no-cost rule
  end to end, through the repository that decides which costs exist rather than in the composer
  alone, and — the one performance assertion in the backend suite —
  `test_the_window_is_not_scanned_more_times_than_it_has_to_be` counts the SELECTs that touch
  `logistics_transaction` during one build. Each is a full scan over a workspace's history, and
  the page once reached its day buckets through the whole P&L statement: nine passes to draw a
  chart that reads two of them. The bound is loose on purpose — it exists to catch a second
  `get_statement` creeping back in, not to freeze a query plan.
* `finreports/` (the rollup and the daily tail) — `test_rollup_rebuild_lock.py` opens two real
  transactions to show a detail write waiting for a rollup rebuild in flight (the advisory lock
  in `repos/pnl/rollup_lock.py`), and fails without the lock. `test_daily_settlement_repository.py`
  owns the daily tail's SQL: the row fingerprint, the upsert that clears a verdict, the
  age-ordered queue, the scoped verdict write. `test_sizes_match_the_article.py` compares Σ size
  rows with the per-article aggregate in real SQL, column by column — the two are separate copies
  of the same expressions.
  `test_rollup_matches_the_detail.py` owns the settlement rollup — the pre-summed copy that made
  «Вся история» (all history) a page instead of a timeout. It pins the SAFETY property rather than
  the speed: every read verifies the rollup against the detail's own row counts and rebuilds
  whatever disagrees, so stale, partial, empty and hand-edited all have to cost time and nothing
  else. A row rewritten in place keeps the count, so the detail's upsert forgets the days it
  touched — the weekly report re-keying the daily lane's rows is that case, and a test pins it.
  All five cuts are compared figure-for-figure against `aggregate_from_detail`, which is what
  catches the slice that derives the stored columns from the aggregate's own expressions
  drifting. The freshness check is memoised per session, so the tests that mutate the detail
  re-read through a FRESH repository — that is what a second request is.
* `contracts/` — schema-driven tests over the generated `openapi.json` (see §5).
* `celery/` — task registration by name, every beat entry resolving, Moscow timezone, JSON-only
  payloads, late acknowledgement, and **cross-task event-loop isolation** with a bare
  `asyncio.run` reproduced as a negative control — including consecutive tasks that each issue
  concurrent Redis commands through the real `get_redis()`.

---

## 2. Frontend

Unit specs are colocated (`store.js` → `store.spec.js`) and cover the axios client, formatting and
date helpers, the auth guard and store, the metrics matrix, the table components, and the charts.

`metricChart.spec.js` owns the chart's arithmetic, which is all lookup and layout rather than
maths: reading a metric at the day-major stride (the wrong stride returns another bucket's number
and renders perfectly happily), the mini-block rows that carry one cell per day instead, and the
axis rules the charts were rebuilt around — one axis per UNIT so metrics that can be compared
share a ruler, ordered ₽ / шт / % rather than by whichever chip was clicked first, sized from the
axes actually DRAWN (index mode draws one whatever was picked, and sizing per unit left a gaping
left margin that jumped when a pick added a unit without adding an axis). It also owns index
mode's baseline — the first day that REPORTED, not day one — and that stock, carts and orders
are columns standing side by side, never stacked into a total in which a cart is a unit of stock.

`components/MetricsChart.spec.js` owns what the picker does to the plot: a ticked chip becomes a
series, an empty selection asks for one instead of drawing empty axes, a blank period says so
distinctly, and the mode switch replots against the index. It also pins the frozen column — the
chart renders twice, and the scrolling copy must hide the labels the pinned copy carries.

`useMatrixEditing.spec.js` owns the daily table's editing surface: that the matrix is exposed by
IDENTITY (the store patches cells in place, so re-wrapping would re-render the whole table on
every keystroke), that saving and refreshing both lock editing, that commits reach the store
untouched, and that the undo/redo keys go quiet while a save is in flight.

`axios.spec.js` additionally owns which Content-Type a request goes out under. The instance
default is JSON, and an instance default outranks the type Axios infers per request, so a
`FormData` body silently shipped as `application/json` — boundary-less, therefore fieldless to
the server, and refused as a malformed request rather than a bad file. That broke every A/B photo
upload in the browser while the whole unit and component tier stayed green, so the pair of
assertions here is *both* directions: FormData must not be JSON, and an ordinary object still
must be.

`abTests/store.spec.js` owns the other half of that incident — what the user is told when an
upload is refused. The result table renders from `variants` alone, so a failed upload paints an
empty table, which reads as "no photos yet" rather than "that did not work": the store must put
the server's message in `error`, keep the photos that already landed, clear the message once one
succeeds, and release `saving` on the failing path (it disables the file input, so a stuck flag
locks the user out of the retry the error is asking for). It also owns the photos' object URLs:
the image route is authenticated and the access token lives in memory, so `<img src="/api/…">` is
answered 401 — the bytes come through the API client and reach the tag as object URLs. That makes
their lifetime the store's problem, so the revoke is pinned in both directions (a reload replaces
them, leaving the view releases them), and one unfetchable photo leaves its row rendering rather
than blanking the rotation.

`finreports/reportFreshness.spec.js` owns the P&L's freshness line, and almost every assertion in
it is a negative, because the line exists to stop a page reassuring from evidence it does not
have: a failed check is never phrased as «нового ничего нет» (WB not answering is an unanswered
question), a check nobody has repeated in over a day switches to a warning tone, a missing record
says so rather than implying calm, and an outcome the build does not recognise is not narrated at
all. It also pins the two date rules that produce plausible wrong answers rather than errors — a
report's period is a calendar date and must never be shifted through `Date`, while an instant's
day and time must come off the same local one — and that a quiet week reads as normal, since a
permanent warning is read as decoration by the second week.

`finreports/store.spec.js` owns what «Обновить» does. Two rules, and the first is why the second
exists at all. **The click answers in one round trip and never waits**: a rate-limited click
renders the minutes to wait, enqueues nothing and leaves no note, and every other click hands the
button straight back — it used to stay disabled for the length of the harvest, which on a WB block
meant minutes of «Обновляем…» (refreshing) over a walk doing nothing. What the seller learns
afterwards comes from a background watcher that disables nothing, so the tests pin that the
statement still reloads itself when a week lands. **And the watcher survives a reload**, which
took **two** sources and the tests say why neither is enough. The harvest lock is the only thing
that knows about a run somebody else started, but it is held by the TASK, not the click — nothing
holds it before a worker picks the job up or after the task ends, and a reload in either window
used to drop the state. So the click is also written down (`pendingRefresh.js`), which is what
lets a reload after the run report its OUTCOME rather than nothing. The baseline for «Загружен
отчёт по …» (report loaded up to …) rides on that note: it is the settlement day at the CLICK,
never the one on screen at the reload, or a week that genuinely arrived is announced as «новых
отчётов нет» (no new reports). The note is cleared at every ending and expires with the poll's
own budget — a worker killed mid-task holds no lock and finishes nothing, and a note without an
expiry would disable the button for good. One poll loop per harvest, too: two would fire the
statement reload twice over one arrival.

Two specs belong to «Поиск по кластерам» and own one product rule each.
`clusterStore.spec.js`: the block's two halves fail independently — a throttled probe must leave
the harvested cluster table on screen — and a rank never survives a SKU switch, since the number
described the previous card. `SkuClusterBlock.spec.js`: the cluster table renders without anyone
typing, and «WB не ответил» (WB did not answer), «нет в первых N позициях» (not in the first N
positions) and a found rank stay three distinct states, because the first two lead a seller to
opposite decisions about the bid.

`csp.spec.js` is the exception to that tier's usual shape — it reads a config file rather than
running the app, because the deployed `Content-Security-Policy` is the one behaviour NO other
tier can observe. The Vite dev server sends no CSP, so a directive that blocks a real feature is
invisible in development and on every unit, component and integration run, and only bites once
nginx serves the app. `img-src 'self' data:` once blanked every A/B thumbnail that way — the
photos are fetched as blobs, `blob:` was not listed, and the browser reported it only as a
console violation and a `naturalWidth` of 0 while the element stayed "visible". It also pins the
off-origin hosts named in *any* directive to an **exact list** — today just
`img-src https://*.wbbasket.ru`, the WB CDN the SKU thumbnails load from — rather than asserting
there are none. An exact list still fails on the next CDN somebody reaches for, and additionally
fails if WB creeps out of `img-src` into `script-src` or `connect-src`.

`hsts.spec.js` reads `tls-headers.conf` for the same reason and a sharper one: weakening HSTS
breaks nothing, warns nobody and produces no console violation — it only shortens how long a
browser refuses plain HTTP, which is a property whose absence looks exactly like its presence.
A floor of one year rather than the exact value (so raising it is not a test change),
`includeSubDomains`, and that `preload` has not silently appeared — that absence is a decision
whose reversal takes months rather than a max-age.

`frontend/tests/integration/` otherwise holds only flows with no single owning file:

| Spec | Spans |
| --- | --- |
| `auth-session-flow.spec.js` | Interceptors + api + store: login, bootstrap with transient-failure retries, mid-session refresh-and-retry, proactive rotation, logout resilience |
| `workspace-context.spec.js` | Selection → `localStorage` → the `X-Workspace-Id` header; recovery from a deleted workspace; the dev-role gate; single-flight loading |
| `router-guard.spec.js` | Real router + real guard + real store: protected-route redirects, guest-only bounces, open-redirect sanitization, session death mid-use |
| `architecture.spec.js` | What ESLint cannot express: the 250-line component limit, a public API per module, no deep cross-module imports |

---

## 3. End-to-end — `tests/end-to-end/`

Four journeys, and they stay few:

* `users/auth-journey.spec.js` — guest redirect and return, bad credentials, session surviving a
  reload, the refresh cookie's real flags read from the browser's jar, logout being final.
* `monitoring/main-flow.spec.js` — the morning flow: log in → monitoring → find a SKU by vendor
  code; switching workspace re-scopes `X-Workspace-Id` and survives a reload.
* `finreports/pnl-dashboard.spec.js` — the P&L landing page resolves against the real API (no
  eternal «Считаем отчёт…», "building the report") and renders its cards and the per-SKU table.
* `ab-tests/photo-rotation.spec.js` — create a test, upload photos through a real file input, and
  read the thumbnail back through our own image route. It stops short of the rotation itself:
  advancing needs 10 000 advertising impressions and a media write against a live seller card.

`fixtures/app.js` logs in through the real form rather than injecting a token — the form, the
cookie, the guard and the workspace bootstrap are the chain these tests protect. It also provides
`openMenu()`, because every nav affordance lives behind the header's burger control, and it
absorbs one auth-rate-limit throttle with a windowed retry (see `tier-contracts.md`, end-to-end).

**Setup:** `npm install && npm run setup:e2e` (Chromium, ~150 MB).
**Credentials:** `E2E_EMAIL` / `E2E_PASSWORD`, defaulting to the seeded `dev-preview@example.com`.
**Data:** `scripts.seed_e2e_fixtures` writes the demo shop (`scripts/seed_demo/`) into the
account's primary workspace, so the journeys run against the same articles `make demo` shows.

---

## 4. Performance — `tests/performance/`

pytest probes cover the connection pool (saturation failing fast, recovery, healthy bursts
queueing, `idle_in_transaction_session_timeout` present, cancelled work leaking nothing) and write
races (concurrent note saves converging on one row, duplicate-registration, a refresh token
consumable exactly once under 20-way contention). Playwright covers "the app loads forever":
dead backend, hanging backend, empty-body 500, and first paint not blocked behind the session
request. k6 holds the load/spike/flood profiles.

### The measured budgets these hold

| Backend state | Before | Now |
| --- | --- | --- |
| First paint (header) | ~0.4 s | ~1.5 s, never blocked behind the session request |
| Refuses connections | ~5.5 s → `/login` | **~3.1 s** |
| Accepts and never answers | ~50 s → `/login` | **~12 s** |

The 50 s came from `/refresh` sharing the 15 s timeout meant for the finreports report,
multiplied by a 1 s / 3 s retry ladder. The auth surface now has its own `AUTH_TIMEOUT_MS` (3 s —
a healthy refresh measures ~3 ms) and a 0.4 s / 1 s ladder. Two retries remain on purpose, so a
backend restarting mid-release does not log everyone out.

k6 thresholds are **objectives, not observations**; all four profiles have been executed green
against a running stack, including the spike to 120 VUs returning 0 5xx and 0 resets, and
`auth-flood.js` serving exactly the limiter's budget out of 1802 attempts with nothing
authenticated. k6 itself is not installed by the repo (`brew install k6`).

---

## 5. Contract testing — current status

`integration/contracts/` guards the generated `openapi.json`: consumed routes still exist,
consumed fields are still present, scalars the SPA renders are still required, protected routes
declare a security scheme, every operation documents a failure mode, and no WB token schema is
reachable from a route.

**This guards the API ↔ SPA boundary, not module-to-module calls.** The monolith has no
cross-module HTTP or queue calls — modules talk in-process through `contract.py`, where a breaking
change is caught by `mypy --strict` rather than a schema. The SPA is the only consumer generating
its client from the document (`npm run types:api`), so it is the only one that can silently drift.
**When a module starts calling another over HTTP or a queue**, add its consumer-driven contract
here and replace this note.

---

## 6. Known gaps

Recorded deliberately rather than left implicit.

| Gap | Why it is open |
| --- | --- |
| No live WildBerries tests | Needs seller tokens, is limited to ~1 request/minute, and would make the suite depend on a third party. Clients are covered against canned envelopes copied from observed responses. |
| Celery tasks are tested for wiring, not execution | The task bodies are thin orchestration over services that are covered directly; running them would need a broker and a full harvest. The one exception is `harvest_workspace`, whose *transaction* shape is logic rather than wiring — `test_harvest_is_atomic.py` runs it for real, with `AsyncSessionLocal` pointed at the test connection and the WB clients faked. That is the pattern to copy when another task grows a property its services cannot own. |
| No visual-regression tests | The `design-system` skill's rules are not machine-checked. Component tests assert structure and behaviour, not pixels. |
| `uq_users_email_lower` is exempt from the migration-drift diff | A functional `lower(email)` index that declarative models cannot express and autogenerate cannot reflect, so every diff proposes dropping it. It has its own positive test asserting the constraint is really enforced, so the exemption cannot hide a loss. |
| List envelopes are optional in the generated client types | `items: list[X] = Field(default_factory=list)` emits neither `required` nor `default`, so the SPA types them as possibly-undefined. Harmless for lists the UI iterates; the contract test enforces required-ness on scalars only. |
| The end-to-end tier is capped at ~10 authenticated tests per minute | Refresh rotation makes `storageState` reuse unsafe (a replayed cookie is a breach), so every test logs in, and the auth limiter allows 10 attempts / 60 s per IP. The fixture absorbs one throttle; beyond that the tier must stay small — which is the right pressure for an e2e suite anyway. |
| The Trivy scan's own invocation is unverified locally | `base-image-freshness.yml`'s loop and all three exit-code branches (clean / vulnerable / tool-failure) were exercised against a stub, but CI is the scan's first real execution. The branches exist precisely so that a first run reporting "the scan did not run" is legible as a tool failure rather than as a finding. |
| The password-reset and email-confirmation flows are tested up to the send | With `EMAIL_ENABLED` false the transport is the logging one. Everything up to the send is covered — code issue, hashing at rest, TTL, attempt cap, single use, session revocation on reset, and the uniform "we have sent one if it exists" answer. What is untested is that a real relay accepts the message, which needs credentials rather than a test. |
