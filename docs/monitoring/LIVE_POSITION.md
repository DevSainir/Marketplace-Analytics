# "Search position" — what we learned, and why it was removed

Written 2026-08-27, immediately **before** the feature was deleted, so that six weeks of
measurement against WB's storefront edge survive the removal. The behaviour described here
was measured live against WB, on the dates given; nothing in this file is inferred. Figures
that would describe a particular seller's catalogue (SKUs, their positions, result counts
for their phrases) are left out or marked as illustrative.

The search-**cluster** panel ("Search clusters", built from harvested advertising
statistics) is unaffected and stays. What went is the **live organic rank probe** — the
part that talked to WB's public storefront in real time.

---

## 1. What the feature was

Three surfaces over one mechanism — scan WB's public search results for a phrase and find
where a SKU sits in the ranked list:

| Surface | Route | Behaviour |
| --- | --- | --- |
| "Check position" | `POST /skus/{nm_id}/search-position/checks` → 202 | Queue one live probe, poll for the result |
| "Search position" | `GET /skus/{nm_id}/search-position` | Read the cached sample, 404 if none |
| "Pin" | `GET/POST/DELETE /skus/{nm_id}/pinned-keywords` | Standing phrases, re-probed on a schedule |
| "Check all positions" | `POST /positions/refresh` → 202 | Re-probe every pinned phrase of the workspace |
| poll | `GET /skus/{nm_id}/search-position/checks` | Re-attach to a running check after a reload |

State lived in three places: `monitoring.pinned_keyword` (durable pins + last known
position), a Redis probe cache (10 min, keyed by **phrase + dest**, never by SKU), and a
Redis run-marker keyed by (workspace, SKU) so a page reload re-attached to a check the tab
that started it no longer owned. Scheduled runs fired three times a day, at
**06:00 / 11:00 / 18:00 MSK**.

---

## 2. The central finding: the session is the whole game

WB's `wbaas` edge does **not** judge this request by its IP, its headers, its HTTP version
or its host. It judges whether the caller carries a session token it issued.

Measured 2026-08-17 from the service's own datacenter address, no proxy:

| What was attached | Result |
| --- | --- |
| Nothing (every header variation we could think of) | **~1 request in 3** answered; the rest 429, retries running to minutes |
| A real browser cookie session | **10 of 10** at ~180 ms — then revoked ~30 min into server-side use |
| An **iOS app** `X-Wbaas-Token` | **20 of 20**, and still serving days later |

Everything else we tried across six weeks — pacing, rotating residential exits, a fresh
tunnel per request, flattened retry ladders, four API versions — was the same problem
attacked from the wrong side. Each moved the number a little. The token moved it to all of
them.

### The token itself

`x_wbaas_token` is dot-separated; its third segment is base64 and self-describing
(the values below are illustrative):

```
0|198.51.100.21|Mozilla/5.0 (Macintosh…)|1787198815|reusable|…|1787069215|1
  ^ issuing IP     ^ issuing User-Agent    ^ expires  ^ reusable ^ issued
```

Three properties, all verified rather than assumed:

* **`reusable`, ~36 h life.** One mint serves tens of thousands of requests. Acquiring it
  is a daily job, not a per-request one.
* **The issuing IP is recorded, not enforced.** The same token answered 200 from the
  laptop that minted it *and* from the server — two addresses on different networks, in
  different countries' worth of routing. We predicted this would fail. It did not.
* **The User-Agent is enforced.** It is part of the payload, so the client must replay the
  exact UA the token was minted with. A mismatched pair presents a session that
  contradicts itself.

### App token vs website token

The iOS app's token is strictly better and markedly cheaper to carry:

* A **subtractive bisect over the app's entire header set** left exactly two headers the
  edge insists on: `X-Wbaas-Token` and `User-Agent`. **`X-Pow` is not required** — that
  was a genuine surprise and is the single most useful thing in this file if anyone
  revisits.
* No cookie jar, no device id, no proof-of-work.
* It reaches the Russian catalogue via `api-ios.wildberries.ru/__internal/search/exactmatch/ru/common/v14/search`
  and **restores `total`**, which the website's v18 dropped.
* The website's cookie session, by contrast, was **revoked about half an hour into
  server-side use** and was dead afterwards even from the laptop whose browser minted it —
  long before its declared 72 h.

### Minting is not possible; copying is

WB issues the token from JavaScript, and **the challenge detects headless Chromium**.
Playwright's default UA announces `HeadlessChrome/131`, and a token minted under it was
refused 403 on every request (2026-08-18) — the edge doing exactly what the string invites.
Substituting the same build's ordinary desktop UA was not sufficient either.

So the token had to be **copied, not minted**: intercept the phone's traffic (Proxyman,
Charles), copy the `X-Wbaas-Token` header, store it in Redis. About a minute of manual
work, **every 36 hours, forever**.

This is the fact that killed the feature (see §7). Reviving it would need a steady supply
of app tokens — in practice, a physical phone whose traffic someone keeps capturing.

---

## 3. The API version is load-bearing, and WB retires versions without notice

Lived through twice:

* **2026-08-14** — `v14` served full pages while `v13` and `v5` answered 429 to everything.
* **2026-08-17** — `v14` itself began refusing every request (every IP, direct and
  proxied, with and without the storefront's headers) while **`v18` answered 200 with 100
  products in the same minute**.

> **A retired version is indistinguishable from a rate limit.** It answers 429 to
> everything. When 429s go universal, **check the version before blaming the IP.**

That mistake cost most of a day, produced two wrong diagnoses (first "a burst problem",
then "a proxy problem") and one shipped-then-reverted default. It is why the path was a
settings knob (`wb_search_path`) rather than a constant.

Envelope differences worth knowing: v18 keeps `metadata.normquery` and `products[].id` but
**drops `total`**. A missing total means UNKNOWN, never "no results" — treating it as zero
tells a seller their card is nowhere when the scan simply stopped early.

---

## 4. A throttled request is not always a 429

Verified live: the same phrase was answered **HTTP 200, ordinary metadata envelope, zero
products, `total: 0`** — and then **100 products with a six-figure `total` one minute
later**.

No field separates that from a phrase WB genuinely finds nothing for. So an empty **first**
page was never passed through as a result; it was treated as a block. Reporting it honestly
would have told the seller every SKU was unranked.

Keep this rule if the feature ever returns. It is not defensive coding; it is the only
correct reading of the evidence.

---

## 5. Rate limiting: reputation, not quota — and our own traffic shape was the problem

* The edge scores **IP reputation and escalates**. Once warm, the server's address collected
  **498** from the storefront and **429** from the search host. No header announces the
  limit and no parameter talks it down.
* Back-to-back requests were refused **even at one per 25 s**. Roughly **one per minute**
  was sustainable anonymously.
* **The single biggest cause of "429 on every second try" was us.** The probe fetched up to
  three pages with no gap, so one button press put three requests on the wire inside a
  second — tripping the edge on the probe's own first page and leaving the next press
  inside the penalty window it had just created. Confirmed 2026-08-17, when the same volume
  from a browser was being served fine and a storefront load from the same IP returned WB's
  "suspicious activity" page with a countdown.

Fixes that worked, and are worth reusing:

* **A shared Redis token bucket** (`search_rate_gate`, capacity 1, ~1 slot per 30 s)
  consulted before *every* attempt, retries included, and shared by the api process and the
  Celery worker — because WB meters the IP they share.
* **Depth cut from 3 pages to 1** (top 100). Depth was buying rank 101–300 at triple the
  requests, triple the budget and triple the odds of ending in "try again in a minute". A
  card outside the first hundred is not being found by shoppers either, so "not in the
  first hundred" is the same decision for the seller as "not in the first three hundred",
  at a third of the cost.
* **Two retry ladders, opposite trades.** Interactive: 1 retry, 30 s backoff — because
  someone is watching a spinner, and **a 1.5 s retry was refused every single time**
  (`429, retry 1/1 in 1.5s, 429`, whole probe dead in two seconds): this host's window is
  tens of seconds, so retrying inside it spends an attempt to learn nothing. Scheduled:
  5 retries — nobody is watching, so outlasting several throttle windows beats returning
  early with nothing. Note that **attempts are not independent** (a proxy pool's addresses
  burn together), so the extra retries buy less than the arithmetic suggests.

---

## 6. Things we got wrong, and the method lesson from each

**The proxy flip-flopped twice.** direct → residential rotation → direct.

On **2026-08-15** a **two-request** comparison (direct 200 vs proxied 429) said direct won,
and we shipped the default on it. That sample was taken *while v14 was being retired*, so
it measured noise from a variable we did not know was moving. What actually holds
(2026-08-17): with a session, the server's own datacenter address answers **10 of 10 at
~180 ms**; a residential exit buys nothing a session does not buy outright and costs
~450 KB of billed traffic per v18 page (~216 KB on v14 — v18 doubled it by carrying each
product's sizes).

> Two lessons, both cheap to state and expensive to learn: **never conclude from a
> two-request sample**, and **never measure while another variable is moving.**

**Regionalisation was assumed and is mostly false.** Within Russia the ranking is **not**
regionalised — four different `dest` values returned a byte-identical top 100. But a
**non-Russian storefront is a different catalogue entirely**: `.kg` returned a markedly
smaller result set for the same phrase, and the same SKU sat at a very different position.
That is the first thing to check when a seller disputes a position. `dest=1259570991`
(Moscow) is what the storefront itself sends, and a position is only meaningful together
with its `dest` and `spp` — which is why the cache key carried `dest`.

**`normquery` is not cosmetic.** `metadata.normquery` is WB's own normalisation of the
phrase and can reorder it ("socks men's" → "men's socks", in WB's Russian). It is the key the
advertising clusters are filed under, and therefore the only thing that let a live probe
line up against harvested cluster data. If the cluster panel ever needs to join against
anything live, this is the join key.

---

## 7. Why it was removed

Removed 2026-08-27 as part of the work opening the product to teams outside our own. The
feature worked; it does not survive multi-tenancy:

1. **It depends on a hand-copied credential that expires every 36 hours.** The token cannot
   be minted (headless is detected, §2), so keeping the panel alive means a person
   intercepting a phone's traffic twice a day, forever. No tenant can do that, and we
   cannot do it on their behalf at scale.
2. **The budget is per-IP and therefore shared by every tenant.** All requests leave from
   one address, metered as one reputation. One team pressing "Check all positions" spends
   the budget of every other team — and the failure it causes them is indistinguishable
   from WB being down.
3. **Its failure mode is the worst kind.** A throttled probe can return HTTP 200 with an
   empty page (§4). Every guard we built exists to stop a rate limit being rendered as
   "your product is nowhere to be found" — a plausible,
   wrong, commercially alarming answer.
4. **The dependency is unofficial and moves without notice.** Two version retirements in
   four days (§3), each initially misdiagnosed.

The scheduled runs, the Redis bucket, the session store, the daily minting container and
the ~20 tuning knobs were all infrastructure serving one number on a card.

---

## 8. If we ever revisit it

The shortest viable path, in order:

1. **Solve the token supply first.** Everything else is already solved and none of it
   matters without this. A sustainable source of app tokens is the entire project; treat
   any work that starts anywhere else as premature.
2. **Keep the version a settings knob** and check it first when 429s go universal (§3).
3. **Keep the async shape**: 202 + poll, with the run marker in Redis keyed by
   (workspace, SKU). Retries take minutes — longer than any HTTP request should live — and
   a held-open request lost the work whenever the seller left the page.
4. **Keep one-scan-many-SKUs.** Pins grouped by phrase, and the probe looks for the whole
   workspace catalogue in pages it already fetched: ten SKUs pinned to one phrase cost one
   scan, not ten. This is the only reason a three-a-day schedule was affordable.
5. **Keep per-phrase transactions.** A run interrupted at phrase 12 keeps the eleven
   results it already paid WB's budget for.
6. **Keep the shared token bucket across processes**, not an in-process semaphore — WB
   meters the IP that api and worker share.
7. **Keep the "withheld" list.** Counters alone cannot separate "nothing to do" from "WB
   refused everything", and a task that reports SUCCESS either way leaves a seller staring
   at an unchanged timestamp with nothing to explain it. The same applies to the per-run
   phrase ceiling: **log truncation when it bites**, or stale cards read as current.
8. **Never merge it into the harvest.** Different host, different bucket, different failure
   meaning — a throttled position must not be able to fail a harvest that succeeded.

---

## 9. Where the code was

For archaeology via `git log` before the removal commit
(`e39171c2`, "refactor(monitoring): drop the live organic-position probe"):

| Area | Path |
| --- | --- |
| Search client | `backend/src/integrations/wildberries/clients/search.py` |
| Session store | `backend/src/integrations/wildberries/search_session.py` |
| Rate gate | `backend/src/integrations/wildberries/rate_limit.py` (`search_rate_gate`) |
| Scheduled run | `backend/src/modules/monitoring/tasks/positions.py` |
| Probe cache | `backend/src/modules/monitoring/services/analytics/position_cache.py` |
| Pins | `backend/src/modules/monitoring/{models,repos}/pinned_keywords.py` |
| HTTP surface | `backend/src/modules/monitoring/routers/clusters.py` |
| Settings | `backend/src/core/config/storefront.py` (`wb_search_*`) |
| Token capture | `backend/scripts/set_search_session.py`, `backend/scripts/mint_search_session.py` |
| Minting container | `backend/docker/docker-compose.yml` (`session_minter`), `backend/docker/Dockerfile` |
