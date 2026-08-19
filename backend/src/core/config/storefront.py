"""Public WildBerries storefront settings: the card and search endpoints.

The two surfaces a shopper's browser talks to (``card.wb.ru`` and
``search.wb.ru``), which no seller API can answer for: the final price after
WB's own loyalty discount, and the organic ranking of a phrase. They are
unauthenticated, sit behind the same anti-bot edge, and share a proxy setting
— which is why they are configured together and apart from the seller APIs in
:mod:`src.core.config.wildberries`.

Almost every default below is a measurement rather than a preference; the
comments record what was measured and when, because each one has already been
set the other way at least once.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class StorefrontSettings(BaseSettings):
    """Card and search endpoint hosts, proxying, timeouts and probe budgets."""

    # --- Card endpoint (final customer price) ---
    # Public storefront card endpoint (card.wb.ru) — the final customer price
    # after ALL discounts incl. WB loyalty (СПП). Unauthenticated. ``dest`` is a
    # region/delivery code and ``spp`` the loyalty tier the storefront prices
    # against; both are fixed inputs the СПП is computed relative to.
    wb_card_base_url: str = Field(default="https://card.wb.ru")
    wb_card_dest: int = Field(default=-1255563)
    wb_card_spp: int = Field(default=30)
    # Optional forward proxy for card.wb.ru ONLY (the other WB surfaces are
    # authenticated seller APIs reached directly). The public storefront edge
    # IP-blocks datacenter egress (prod started getting HTTP 403 on 2026-07-14);
    # a residential/mobile proxy restores the clean egress IP. curl still
    # supplies the TLS fingerprint that clears the anti-bot filter — the proxy
    # only swaps the IP. EMPTY = direct connection (correct for a clean local
    # IP). Holds credentials → lives in .env, never committed.
    wb_card_proxy: str = Field(default="")
    # Strict connect timeout for the (slow, fragile) proxy tunnel — separate
    # from the whole-request cap so a dead tunnel fails fast instead of burning
    # the full timeout budget (bounds proxy traffic/cost on failure).
    wb_card_connect_timeout_seconds: float = Field(default=15.0)
    # Tighter retry cap than the rate-limited seller APIs: a broken proxy must
    # give up quickly instead of spinning (protects the proxy balance).
    wb_card_max_retries: int = Field(default=3)
    # --- Search endpoint (organic ranking) ---
    # Public storefront SEARCH endpoint (search.wb.ru) — the organic ranking a
    # shopper sees, which no seller API exposes. Unauthenticated, and behind the
    # same anti-bot edge as the card endpoint, whose proxy it inherits (see
    # ``wb_search_proxy``). Its timeout and retry budget are its OWN, and far
    # tighter, because this surface is read while a user waits.
    # The bare API host, NOT the storefront's own `/__internal/u-search/` route.
    #
    # The internal route is strictly better when a session is in hand (10/10 at
    # ~180 ms) and strictly useless without one — it answers 403 to every
    # anonymous request. And a session cannot currently be kept: a token copied
    # from a real browser was revoked about half an hour into server-side use
    # (measured 2026-08-18, dead afterwards from the VPS *and* from the laptop
    # that minted it, long before its declared 72 h), while minting one here is
    # blocked by the headless detection described in scripts/set_search_session.py.
    #
    # So the default has to be the host that answers anonymously, even though it
    # answers only about one request in three. Point this pair at the internal
    # route the day a session can be sustained; the client already attaches one
    # whenever the store holds it.
    wb_search_base_url: str = Field(default="https://search.wb.ru")
    # A knob because WB retires versions abruptly, and a retired one is
    # indistinguishable from a rate limit — it answers 429 to everything (v14 did
    # exactly that between 2026-08-14 and 2026-08-17, while v18 served 100
    # products in the same minute). See clients/search.py.
    wb_search_path: str = Field(default="/exactmatch/ru/common/v18/search")
    # Delivery region the ranking is computed for — the value the storefront
    # itself sends for Moscow. Within Russia the ranking is NOT regionalized
    # (verified across four dests, byte-identical top 100), but a non-Russian
    # storefront is a different catalogue entirely (.kg: 5 178 results against
    # 7 486, the same SKU at 53 instead of 26) — the first thing to check when a
    # seller disputes a position. Details in the wildberries-api skill.
    wb_search_dest: int = Field(default=1259570991)
    # The iOS app's search surface, used INSTEAD of the two above whenever a
    # session holds an app token. It answers from our own datacenter IP with no
    # proxy, needs no cookie jar, and returns `total` (which the website's v18
    # dropped) — but it refuses every request without `X-Wbaas-Token`, so it is
    # useless anonymously. See integrations/wildberries/search_session.py.
    wb_search_mobile_base_url: str = Field(default="https://api-ios.wildberries.ru")
    wb_search_mobile_path: str = Field(default="/__internal/search/exactmatch/ru/common/v14/search")
    # Result slots per page; 100 is what the storefront itself requests.
    wb_search_page_size: int = Field(default=100, ge=1, le=300)
    # How deep a position probe may scan — ONE page, the top 100.
    #
    # Was 3. Each page is a separate request against a host that refuses roughly
    # two attempts in three, so depth was buying rank 101-300 at the price of
    # tripling the requests, tripling the rate-budget spend, and tripling the
    # chances of a check ending in «повторите через минуту». A card outside the
    # first 100 is not being found by shoppers either, so "не в первой сотне" is
    # the same decision for the seller as "не в первых трёхстах" — at a third of
    # the cost.
    wb_search_max_pages: int = Field(default=1, ge=1, le=20)
    # Gap between phrases in a scheduled pinned-position run. Not politeness:
    # this host answers back-to-back requests with 429 even one per 25 s (see
    # the search client's module docstring), so a run that hurries returns
    # nothing at all. One phrase a minute is what measured as sustainable.
    wb_search_probe_spacing_seconds: float = Field(default=60.0, ge=0)
    # Phrases one scheduled run may probe, per workspace. At the spacing above
    # this is the run's wall-clock budget (60 = about an hour). Pins beyond it
    # keep their previous position and are named in the run's log — a silently
    # truncated run would leave stale cards looking current.
    wb_search_max_keywords_per_run: int = Field(default=60, ge=1)
    # How long a keyword's probe result is reused (Redis). The ranking moves
    # within the hour, so this trades freshness for not being throttled: a team
    # of five checking the same phrase pays for one probe.
    wb_search_cache_seconds: int = Field(default=600, ge=0)
    # Forward proxy for the public search host. ``card`` (the default) reuses
    # ``wb_card_proxy``; ``direct`` forces a direct connection; any other value is
    # used as the proxy URL; empty means direct too.
    #
    # DIRECT, and this setting has now been through the full argument. It was
    # direct, then proxied (rotation being the only lever against an IP-reputation
    # block), and it is direct again for a better reason than either: the block was
    # never really about the IP. Measured 2026-08-17 from the VPS's own datacenter
    # address, no proxy, carrying a browser session — 10 of 10 requests answered in
    # ~180 ms, where the same address cookieless managed about one in three. A
    # residential exit bought nothing that a session does not buy outright, and it
    # cost ~450 KB of billed traffic per page.
    #
    # Historical note, since this flip-flopped once on bad evidence: On
    # 2026-08-15 a two-request comparison said direct won (200 direct vs 429
    # proxied) — but that was measured while WB was retiring the API version we
    # were calling, so the sample was noise, and we shipped `direct` on it.
    # What actually holds (2026-08-17): the block is per-IP REPUTATION, not a
    # quota, and it escalates — the VPS address earns HTTP 498 from the storefront
    # and 429 from the search host once warm, while the proxy hands out a fresh
    # residential IP per request (verified: 198.51.100.31 -> 198.51.100.32 ->
    # 198.51.100.33). Since we cannot present a browser's JS-issued wbaas token,
    # a clean IP per probe is the only lever left. It costs ~216 KB of billed
    # traffic per page.
    wb_search_proxy: str = Field(default="direct")
    # Per-request cap for one search page, tighter than the shared 30s: a ranked
    # page is ~220 KB served in well under a second when the host is willing, so
    # a slow read here means throttling, and waiting the full 30s only delays
    # the retry. Bounds the probe's worst case together with the two knobs below
    # (pages x attempts x this + waits), which must stay under the browser's own
    # budget in frontend/src/modules/monitoring/api.js.
    wb_search_timeout_seconds: float = Field(default=12.0, gt=0)
    # Opening the proxy tunnel is the slow part — far slower than the answer —
    # and it gets its own ceiling so the read budget above does not have to be
    # sized for it. A dead tunnel then fails in 20s instead of burning a slot.
    wb_search_connect_timeout_seconds: float = Field(default=20.0, gt=0)
    # Retry budget for ONE search page, deliberately far tighter than the seller
    # APIs' (4). A probe is INTERACTIVE: someone is watching a spinner, and the
    # seller-API ladder (4 retries, 2/4/8/16s backoff, plus a Retry-After WB
    # sets as high as 60s) can push a single page past a minute — three pages
    # past three. Throttling here is the normal state, not an incident, so the
    # probe reports «WB притормозил» quickly and lets the user retry into a
    # warm cache instead of holding the request open.
    wb_search_max_retries: int = Field(default=1, ge=0)
    # The wait before that retry, and it has to be long enough to OUTLAST a
    # throttle window rather than merely to look patient. Measured on prod
    # 2026-08-15: a 1.5s retry was refused every time (429, retry 1/1 in 1.5s,
    # 429 — the whole probe gave up in two seconds) because this host's window is
    # tens of seconds. Retrying inside it spends an attempt to learn nothing.
    # 30s is one window; a second retry would push the worst case past the
    # browser's budget for no extra odds.
    wb_search_retry_backoff_seconds: float = Field(default=30.0, ge=0)
    # The SCHEDULED run's budget, which is the opposite trade: nobody is watching
    # it, so waiting out several throttle windows is strictly better than
    # returning early with nothing. Measured on prod 2026-08-17: the interactive
    # budget (one retry, 30s) lost the only pinned phrase to two consecutive
    # 429s, and the run reported SUCCESS having updated nothing.
    # Five, not three: anonymous success is roughly one attempt in three, and out
    # here the extra minutes cost nothing but the worker's patience. (Attempts are
    # NOT independent — the pool's addresses are burned together — so this buys
    # less than the arithmetic suggests.) Bounded by the per-run keyword ceiling.
    wb_search_task_max_retries: int = Field(default=5, ge=0)
    # NOTE: with a session in hand these ladders almost never engage — a probe is
    # one request that answers in ~200 ms. They remain as the fallback for an
    # expired or missing session, when WB is back to refusing two requests in three.
    #
    # FLAT, not exponential: the ceiling equals the base, so the ladder is
    # 60s + 60s + … rather than 60 + 120 + 120 + 120. Doubling made no sense
    # against a limiter whose window is tens of seconds — it did not improve the
    # odds of the next draw, it just pushed one check to ~9 minutes (observed
    # 2026-08-17 on «брюки мужской»). Five flat waits bound a check at ~5 min,
    # which is a promise the panel can make.
    wb_search_task_retry_backoff_seconds: float = Field(default=60.0, ge=0)
    wb_search_task_retry_max_backoff_seconds: float = Field(default=60.0, ge=0)
    # Ceiling on a single wait. Passed BOTH as the backoff cap and as the
    # client's Retry-After ceiling: a server-demanded wait is otherwise honoured
    # past the backoff cap (correct for the harvest, wrong for a watched
    # request), and an unbounded 900s header would hang the page. Sized so one
    # retry still fits well inside the browser's 120s budget: worst case per page
    # is timeout + wait + timeout = 12 + 30 + 12 = 54s.
    wb_search_retry_max_backoff_seconds: float = Field(default=30.0, ge=0)
    # --- Search rate bucket ---
    # The public search host, whose budget we were spending three times over per
    # button press. Verified 2026-08-17: the probe fetched its pages with no gap
    # at all ("sequential" is not "paced"), so ONE press sent three requests
    # inside a second — enough to trip the edge on its own first page and leave
    # the next press inside the penalty window it had just created. That is what
    # "429 every second try" was.
    #
    # Unlike the seller APIs this is not a published quota but an anti-bot
    # reputation system (a burst earns «Подозрительная активность» with a
    # countdown, IP-wide), so the bucket is deliberately meaner than any measured
    # header: one request at a time, ~30s apart. Capacity 1 means no burst is
    # possible even across the api and worker processes, which share this key —
    # nothing else here coordinates them.
    wb_search_bucket_capacity: int = Field(default=1, ge=1)
    wb_search_bucket_refill_seconds: float = Field(default=30.0, gt=0)
    # Longest a probe may queue for a slot. Sized under the browser's own budget
    # so a watched request that cannot get a slot says «повторите через минуту»
    # instead of timing out: 2 pages x (30s wait + 12s request) fits in 90s.
    wb_search_max_queue_seconds: float = Field(default=90.0, gt=0)
    # Kept as a separate knob, now equal to the scheduled depth: one page is
    # already the right answer for both, and a future deeper scan should have to
    # justify itself on the watched path first.
    wb_search_interactive_max_pages: int = Field(default=1, ge=1, le=20)
