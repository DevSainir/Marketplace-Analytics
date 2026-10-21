# Attack classes, as they actually show up here

Per class: the question to ask, how it has appeared **in this repo**, and how to verify. The
worked examples are real — every one was found in this codebase and fixed, which is why they
are worth more than the generic category names. Where a test now pins the fix, it is named.

Aligned to OWASP Top 10:2025 and the OWASP API Security Top 10, but organised by what you are
about to write rather than by taxonomy.

---

## Horizontal escalation — BOLA / IDOR (API1)

> Can user A pass the id of user B's entity and read, modify or delete it?

The single highest-risk class for this service, and historically its worst bug.

**How it appeared here.** `X-Workspace-Id` was once validated for *existence* only, so the
header WAS the tenancy: changing one value would have reached another seller's funnel data,
settlement P&L, cost prices and stock. It is now checked against the caller's own
organisation (`CurrentWorkspaceId`), and row-level security backs that check in the
database.

**Second form, harder to see.** Cross-module loaders that took no tenant argument let
`GET /pnl/skus` sum every tenant's orders and advertising into the «Итого» (total) row of
whichever tenant asked. No id was forged; the query simply never said whose data it wanted.
`test_export_loaders_are_scoped.py` now fails the build on a loader without a required
keyword-only `workspace_id`.

**Ask:**
* Does every query carry a tenant column, or only an id?
* Does every *aggregate* carry one, including `min`/`max`/`sum` used for "coverage" spans?
* Does everything the response **contains** — files, embedded ids, sibling rows — carry one?
* Would a brand-new empty tenant get an empty answer, or everyone's data? Test that case; it
  is the one an unscoped query hides best.

**Verify:** a test seeding *two* tenants with overlapping data and asserting the second is
invisible. Not a test with one tenant — that passes either way.

---

## Vertical escalation — BFLA (API5)

> Can a lower-privileged or unauthenticated caller reach this path?

**How it appeared here.** Workspace administration — reading and rotating WB API tokens, the
credentials to a seller's live account — was gated on the platform `dev` role while listing
was open to any authenticated user. Neither matched the actual question, which is about the
organisation.

**Ask:**
* Which rung of the ladder is narrowest and still works? Default to narrower.
* Is the guard on the *router* or per-route? Router-level means a new route cannot forget it.
* Does a **write** need `WritingAccess` rather than `MemberAccess`?
* Is the internal-only surface actually internal, or merely undocumented?

**Trap:** a guard that overrides authentication instead of composing with it. In tests, a
fixture replacing the access dependency must still depend on `CurrentUser`, or every
"bad token is a 401" test quietly asserts against an unauthenticated request.

---

## Resource exhaustion (API4)

> Can this be called repeatedly, or with a hostile payload, to drain memory, connections,
> disk, or someone else's API quota?

The WB rate budget is shared platform-wide, so one tenant can starve every other tenant — and
the failure they see is indistinguishable from WB being down.

**How it appeared here**, and what bounds each now:
* A harvest endpoint enqueued work for **every workspace on the platform**; it now enqueues a
  walk scoped to the caller's own workspace (`test_harvest_routes.py`).
* Refresh endpoints enqueued Celery work with no per-caller budget and no dedup; they now
  dedupe identical in-flight requests and spend a per-workspace budget
  (`test_refresh_bounds.py`).
* Uploads did `await file.read()` and *then* checked the size, so the cap did not protect
  memory; `src/core/uploads.py` now refuses while reading (`test_upload_caps.py`).
* `openpyxl.load_workbook` ran on attacker-supplied ZIP bytes with no decompressed-size or row
  cap; both parsers now sum the declared sizes first and cap rows during iteration.
* Request lists (`nm_ids`, matrix `days`) had no length bound; they carry `max_length` now
  (`test_request_bounds.py`, `test_tenant_resource_bounds.py`).
* Celery tasks had no time limit, so one wedged task could hold a worker slot indefinitely;
  every task now has a soft and a hard deadline (`test_task_time_limits.py`).

**Ask:**
* Is the size check **before** the read into memory?
* Is there a bound on every list, page, window and row count?
* Does this spend a *shared* budget (WB quota, broker, worker slots)? Then it needs a
  per-tenant limit, not just a global lock.
* What happens at 1 000 concurrent calls — queue, or fall over?

---

## Race conditions — TOCTOU

> Two requests arrive in the same millisecond. Do they both pass a check that should let
> exactly one through?

Every "only once" rule is a read-then-write unless you make it otherwise, and a
read-then-write has a window between the read and the write in which a second request reads
the same thing.

**How it appeared here.** Activation-code redemption checked `used_at is None`, built an
organisation, then set `used_at`. Two *different* accounts redeeming the same code
concurrently both passed the check — one code sold once produced **two paid organisations**,
with nothing afterwards able to say which was legitimate. Invitation acceptance had the same
shape: one link, two managers. The membership `UNIQUE(user_id)` did not help, because the two
racers were different users.

**The pattern that works** — `RefreshTokenRepository.consume` was already doing it, and its
docstring calls the conditional UPDATE "the linchpin":

```python
stmt = update(X).where(X.id == id_, X.used_at.is_(None)).values(used_at=now)
return int(result.rowcount or 0) == 1   # exactly one caller gets True
```

**Two rules that matter as much as the UPDATE itself:**

1. **Claim before you build.** Consume the credential *first*, then create the organisation.
   Claim-last means the loser has already created an orphan.
2. **The loser gets the ordinary refusal.** A lost race returns "invalid code", not a special
   error — by the time it lost, the code genuinely is spent.

**Ask:** is there a uniqueness, single-use, quota or balance rule here? Could two requests
both satisfy it? Can the database decide instead — conditional `UPDATE`, unique index,
`SELECT ... FOR UPDATE`?

**Verify:** a test that actually races. A sequential test passes even with the bug, because
the first request has committed by the time the second looks. Use two real connections and
`asyncio.gather`. Then break the guard and confirm the test fails — a concurrency test that
cannot fail is decoration.

**Client-side races count too.** Three browser tabs share one cookie jar. Three tabs
refreshing at once send three parallel `/refresh` calls with the *same* refresh secret; the
first rotates, the other two look exactly like a replayed stolen token, and the family is
revoked. The SPA's `refreshPromise` dedup only covers one tab's JS context, so the server
keeps a short replay-grace window in which every racing tab converges on the one live token
(`test_concurrent_tab_refresh.py`), while a replay after the window still kills the lineage
(`test_breach_detection.py`). A security control whose false-positive path logs legitimate
users out is a control that will eventually be turned off.

---

## Decompression and parser bombs

> The input is small. What does it become once parsed?

`.xlsx` is a ZIP container, and `openpyxl` is handed attacker-controlled bytes on the
cost-price import. A 10 MB upload can expand to gigabytes, and a small file can declare
millions of rows.

**Ask:**
* Is the size checked on the **compressed** bytes only? That bounds nothing.
* Sum `ZipFile.infolist()[].file_size` *before* parsing and refuse an absurd expansion ratio.
* Cap the row count during iteration, not after building the list.
* `read_only=True` streams and helps, but does not bound the declared dimensions.
* XML entity expansion — check whether the parser resolves external entities at all.

The same question applies to any format that expands: nested JSON depth, a CSV with a
pathological quote, an image that decodes to a huge bitmap.

---

## Injection and unsafe execution (A03)

SQL here is entirely SQLAlchemy-parameterised; the one raw `text()` is a constant
`SET LOCAL lock_timeout`. Keep it that way — no f-strings into `text()`, ever.

**Also check:**
* **Subprocess** — `card.py` shells out to `curl` via `create_subprocess_exec` with an
  argument *list* and no shell. Never build a command string; never pass `shell=True`.
* **Deserialization** — Celery is JSON-only. Never enable pickle; the broker is Redis and
  pickle there is remote code execution.
* **Path traversal** — a path built from any user-controlled segment must be resolved and
  checked to be inside its root. Stored media paths are digest-derived, which is why they are
  safe; a user-supplied filename would not be.
* **Content-type reflection** — serving an uploaded file back with its *declared* type is
  stored XSS if the type is not allow-listed. The A/B variant store allow-lists five image
  types; `nosniff` is the second layer, not the first.

---

## Data exposure (A01 / A02 / API3)

**Ask before every response:**
* Does this DTO have a field that exists only because the ORM model has it?
* Does an error message contain an upstream body, a file path, a SQL fragment, or a row
  count from another tenant?
* Does a "not found" leak existence? Foreign resources are 404.
* Does a listing leak the *set* of tenants — names, counts, ids?
* **Does a validation error echo what was sent?**

**The 422 trap.** FastAPI's default `RequestValidationError` handler returns each error with
an `input` key holding the offending value, plus a `ctx` that can carry more of it. On this
API that meant POSTing a seven-character password to `/register` came back as
`{"loc": ["body","password"], "input": "hunter2"}` — the password in clear, in a response
body, into devtools and any intermediary's logs. `main.py` overrides the handler to keep
`type`/`loc`/`msg` and drop the rest. `loc` stays on purpose: the client must know which
field it got wrong, and the field names are already public in the schema it just submitted.

A framework default is not a security decision someone made for you. Check what your
framework returns on the error paths, not just the success ones.

**Appeared here:** `GET /workspaces` returned every workspace on the platform, with the
sellers' legal names, to any authenticated account. It also handed out the ids that every
other tenant-scoped route keys on.

---

## Business-flow abuse (API6)

> The endpoint works exactly as designed, and the design is the problem.

**Ask:**
* What does this cost us if automated? (A WB call costs shared quota.)
* Is a single-use credential enforced as single-use *in the database*, or only checked
  before a write that could race?
* Can a flow be replayed — an invitation forwarded, a code shared, a link re-used?
* Does a targeted invitation verify the accepting account matches its target? Without that,
  "I invited my accountant" becomes "someone in my accountant's inbox has our reports".

---

## Authentication and session (A07 / API2)

Rotation with family-scoped breach detection is in place. What to keep in view:

* **Fail-open is a decision, not a default.** The auth rate limiter and the session
  revocation watermark both fail open on a Redis outage. That is defensible for availability
  and it means a Redis outage removes brute-force protection and revocation *at the same
  time* — which is why both report to the degradation ledger, and the ledger raises its own
  event when two controls are down together. A new fail-open control reports there too.
* **A limiter is only as good as its client identity.** `request.client.host` is not one:
  with `--forwarded-allow-ips *`, uvicorn takes the **leftmost** `X-Forwarded-For` entry,
  which the client controls. The limiter keys on the address the reverse proxy writes
  (`src/core/client_ip.py`), and `test_auth_rate_limit_spoofing.py` wraps the app in
  uvicorn's own proxy middleware to prove a forged header neither escapes a spent budget nor
  opens a fresh one.
* **Enumeration.** Login is constant-time and single-messaged, and so is account recovery:
  the request endpoint answers the same whether or not the address is registered.

---

## SSRF and unsafe upstream consumption (API7 / API10)

We call WB, and WB's responses are outside the trust boundary.

* Every WB payload is validated with a Pydantic model before use. A shape change must
  surface as an error, never as a plausible wrong number written to the database.
* A URL built from user input and then fetched is SSRF. All WB base URLs come from settings.
* **A throttled upstream is not always an error.** WB answered HTTP 200 with an empty result
  set while rate-limiting. Treating that as data would have told sellers their products rank
  nowhere. When an upstream's "no results" and "refused" are indistinguishable, treat the
  ambiguous case as a failure.

---

## Supply chain and configuration (A08 / API8 / API9)

* Pinned dependency versions and pinned CI actions (by SHA, not tag — a tag moves).
* A third-party CDN is a script-execution dependency on someone else's infrastructure. This
  app pulls fonts from Google Fonts; that is an allow-listed CSP entry and a supply-chain
  edge.
* Base images go stale silently; rebuild on a schedule, not only on deploy.
* **Inventory is a control.** `/docs`, `/redoc` and `/openapi.json` publish the entire API
  surface, so they are mounted only where a setting allows it, and the three move together —
  hiding the viewers while still serving the schema withholds nothing
  (`test_documentation_exposure.py`). An endpoint nobody remembers is an endpoint nobody
  guards.

---

## Auditability

Not prevention — the ability to answer "what happened" afterwards.

Two different needs, and the second is not satisfied by the first.

**Attribution** — `created_by_user_id` / `updated_by_user_id` on a row. Answers "who last
touched this?" while the row exists, and only while it exists.

**An audit trail** — an append-only record of *events*, independent of the rows they concern.
Attribution alone does not survive the thing it describes: a compromised manager who deletes
every workspace, or removes a member, or rotates a WB token, takes the `updated_by_user_id`
with them — the evidence is destroyed by the same action you are investigating. The record has
to outlive the row.

Security-relevant events need the second kind: who, which organisation, from which IP, when,
and what changed — written once and never updated. Membership changes, credential rotations,
role changes, subscription activations and workspace deletions all qualify. Ordinary business
writes do not; an audit log that records everything is one nobody reads.

Here that is `organizations.audit_log`: insert-only by grant and by trigger, with no foreign
keys on actor or tenant so the entry outlives both. A trigger on `organizations.subscriptions`
records every change even when it is made as raw SQL.

---

## What good looks like

A control that cannot be forgotten beats one that must be remembered:

| Weak | Strong |
| --- | --- |
| Remember to pass `workspace_id` | Required keyword-only argument + a test that reflects over the signatures |
| Check `role == "owner"` in the route | `OwnerAccess` on the router |
| Validate uniqueness before insert | Partial unique index |
| Filter another tenant's rows in Python | Tenant in the `WHERE` |
| Document that a secret is not returned | A DTO with no field for it |
| `assert access.organization_id` | `access.tenant_id`, which raises |
