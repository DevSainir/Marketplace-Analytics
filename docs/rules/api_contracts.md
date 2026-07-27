# Marketplace API Contracts & Business Logic (WildBerries)

> **Status:** Verified against the live WB API on **2026-07-06** with real seller
> tokens. Where the earlier draft of this document disagreed with reality, this
> version reflects what the API actually does. The integration code in
> `backend/src/integrations/wildberries/` matches these contracts.

## 1. Global Constraints
* **Hosts (per API surface):**
    * Analytics (funnel, stocks): `https://seller-analytics-api.wildberries.ru`
    * Advertising (fullstats): `https://advert-api.wildberries.ru`
* **Auth:** each surface uses its own bearer token in the `Authorization`
  header (WB tokens are category-scoped: "Аналитика" vs "Продвижение").
* **Connectivity check:** both hosts expose `GET /ping` → `{"TS", "Status":"OK"}`.
* **Timezones:** WB operates in Moscow Time (UTC+3). Normalize all timestamps to
  UTC+3 before persistence.
* **Current day:** WB does **not** serve statistics for today. Requests that
  include the current date are rejected or empty — always query up to *yesterday*.
* **Data Flattening:** WB returns nested JSON. Worker routines flatten these
  trees into clean relational records.

## 2. API: Sales Funnel — DAILY history (primary source)
* **Endpoint:** `POST /api/analytics/v3/sales-funnel/products/history`
* **Auth:** Analytics token.
* **Request body (both fields required):**
  ```json
  {
    "nmIds": [909379884],
    "selectedPeriod": { "start": "2026-06-29", "end": "2026-07-05" }
  }
  ```
  > Note the **lowercase `nmIds`** on this endpoint (the aggregate endpoint below
  > uses `nmIDs`). Dates are `YYYY-MM-DD`.
* **Rolling window:** this endpoint only serves the **last 7 days**. The `start`
  must be `>= today - 7` and `end <= yesterday`; a window whose start is older
  than 7 days (or that spans more than 7 days) returns HTTP 400 "invalid
  payload". The harvester's default window (yesterday back 7 days) stays inside
  this bound — hardcoding older dates will 400 once they age out.
* **Response (top-level list, one node per product):**
  ```json
  [
    {
      "product": { "nmId": 909379884, "title": "...", "vendorCode": "..." },
      "history": [
        {
          "date": "2026-06-29",
          "openCount": 3544, "cartCount": 250, "orderCount": 105,
          "orderSum": 436228, "buyoutCount": 29, "buyoutSum": 120900,
          "buyoutPercent": 39, "addToCartConversion": 7,
          "cartToOrderConversion": 42, "addToWishlistCount": 78
        }
      ]
    }
  ]
  ```
  > **No impressions.** Verified live (2026-07-08): this feed exposes **no**
  > views/показы/impressions field. `openCount` (card opens) is the top of the
  > organic funnel — "how many times the card was shown in a list" is not
  > obtainable here (nor from the aggregate §3 endpoint, nor the retired
  > nm-report). The only impressions in the whole WB surface are advertising
  > `views` (§4, paid only).
* **Ingestion mapping** → `monitoring.sales_funnel_daily`, one row per
  `(date, nm_id)`: `openCount`→`open_count`, `cartCount`→`cart_count`,
  `orderCount`→`order_count`, `orderSum`→`order_sum`, `buyoutCount`→
  `buyout_count`, `buyoutSum`→`buyout_sum` (buyout revenue ₽),
  `addToWishlistCount`→`add_to_wishlist`, `addToCartConversion`→
  `cart_conversion`, `cartToOrderConversion`→`order_conversion`,
  `buyoutPercent`→`buyout_conversion`.
* **No cancel count.** Verified live (2026-07-16): the daily feed serves
  `buyoutCount` and a whole-number `buyoutPercent`, but **no** `cancelCount` —
  so a day's DECIDED deliveries are not obtainable here. Combined with the
  7-day cap this makes the daily feed unusable as the «Процент выкупа» source:
  its `buyoutCount` freezes ≤7 days after the order date while the real cohort
  keeps maturing for ~3 weeks. `buyout_count` is therefore only SEEDED from
  this feed on insert; §3's cohort pass owns it (and `cancel_count`) after that.

## 3. API: Sales Funnel — period aggregate (the buyout/cancel cohort source)
* **Endpoint:** `POST /api/analytics/v3/sales-funnel/products`
* **Body:** `{"selectedPeriod": {"start", "end"}}`.
* **The `nmIDs` filter is IGNORED** (verified live 2026-07-16): passing a single
  nmID still returns the seller's whole catalogue (40 products, one page — an
  `offset=50` probe returns 0). Filter client-side; do not assume the request
  narrows the response.
* **Arbitrary history, unlike §2.** `start = today - 21` returns HTTP 200 here
  where the daily feed 400s ("invalid start day: excess limit on days"). Called
  with `start == end` it yields ONE matured per-day cohort — the only way to
  re-read an order-date cohort as its deliveries are accepted/refused.
* **Response:** `data.products[].statistic.{selected, past, comparison}` — each a
  period aggregate carrying `openCount/cartCount/orderCount/buyoutCount/
  cancelCount/addToWishlist` and a nested `conversions` object
  (`addToCartPercent/cartToOrderPercent/buyoutPercent`).
* **«Процент выкупа» is defined by the two counts**, not by the percent field:
  `buyoutPercent == buyoutCount / (buyoutCount + cancelCount)` exactly (verified
  live: `567 / (567 + 965) = 37%`, WB reports 37). `cancelCount` is the buyer's
  refusal at pickup — a DECIDED delivery. Store the counts; never round-trip
  through `buyoutPercent`, which is an integer and reads 0 for a zero-buyout
  cohort (whose refusals then vanish from any average).
* **Ingestion** → `monitoring.sales_funnel_daily.{buyout_count, cancel_count}`,
  by the `monitoring.refresh_buyout_cohorts` task (nightly, 07:00 MSK). It walks
  the last `COHORT_REFRESH_DAYS` = 22 days one call per day. It is an UPDATE
  only: a `(date, nm_id)` with no funnel row is skipped, since this endpoint
  answers for every date the seller ever traded and inserting blind would
  fabricate zero-order funnel days.
* **Rate limit:** ~1 request/20s (HTTP 429 otherwise); the client honours
  `Retry-After`. A 22-day pass therefore takes ~7 min — which is why it is a
  scheduled catalogue-wide task and NOT part of the interactive «Обновить»
  refresh (`monitoring.harvest_sku_window`).

### 3a. Refusals (`cancelCount`) vs returns — NOT the same event
A **refusal** (`cancelCount`) is the buyer declining the parcel at pickup: it
kills the delivery, so it never becomes a sale and **never appears in the
Statistics `supplier/sales` feed**. A **return** is the buyer sending an item
back *after* buying it, which does appear there (`saleID` prefix `R`).

«Процент выкупа» divides by DECIDED DELIVERIES — `buyoutCount + cancelCount` —
so it is obtainable **only** from §3. It cannot be reconstructed from
`supplier/sales`, whose denominator (buyouts + returns) is a different, much
smaller population. Measured live 2026-07-16 on nm 953770957: `sale_record` held
274 buyouts / 30 returns (a 90% "buyout share") while WB's own «Процент выкупа»
for the same SKU was ~30%. The two are not reconcilable and must not be
conflated:
* «Процент выкупа» → `sales_funnel_daily.{buyout_count, cancel_count}` → the
  matrix's `buyout_percent` (lagged cohort window). This is the ONLY place it
  exists.
* Sale-date buyout/return VOLUMES → `sale_record` →
  `SkuSummaryItem.{total_buyout_count, total_buyout_sum, total_return_count}`.
  Counts only — the listing deliberately serves **no buyout ratio**. It cannot
  serve «Процент выкупа» (its window is arbitrary: default 30d, max 366d, while
  the cohort pass refreshes `cancel_count` for only the last 22 days), and any
  ratio built from `sale_record` instead would answer a different question while
  looking like an answer to this one. A caller wanting a return rate divides the
  two counts itself.

## 4. API: Advertising Full Stats
* **Endpoint:** `GET /adv/v3/fullstats` (GET only — POST returns 405).
* **Auth:** Advertising token.
* **Query params:** `?ids={id1,id2}&beginDate=YYYY-MM-DD&endDate=YYYY-MM-DD`
  > The params are `beginDate`/`endDate` (an earlier draft's `dateBegin`/
  > `dateEnd` are silently ignored, causing WB to default to today → HTTP 400
  > "Invalid begin date"). Max window **31 days**.
* **Discovery / campaign dimension:** `GET /adv/v1/promotion/count` lists all
  campaigns grouped by `type` + `status`
  (`adverts[].{type,status,advert_list[].advertId}}`). We flatten this into the
  `monitoring.campaigns` table to enable status filtering. Status codes:
  `-1` deleting, `4` ready, `7` completed, `8` declined, `9` active, `11` paused.
  (Campaign **names** are not on this endpoint; `/adv/v1/promotion/adverts`
  returns 404 for this account — names would need the content API.)
* **Rate limit:** aggressively throttled (~1 request/minute/seller → HTTP 429).
  The harvester retries with exponential backoff and honours `Retry-After`.
* **Response processing:** iterate `days[]` → `apps[]` (platforms) → `nms[]`
  (SKUs).
    * `appType`: `1` Desktop, `3` Android, `4` iOS, `10` Mobile Web, `64` ARK.
    * Flatten to `monitoring.advertising_stat_daily`, one row per
      `(date, campaign_id, app_type, nm_id)`: `views, clicks, sum`→`spend`,
      `orders`.

## 5. API: Sales Stocks
* **Endpoint:** `POST /api/analytics/v1/stocks-report/wb-warehouses`
* **Auth:** Analytics token.
* **Request body:** `{"nmIds": [909379884]}`
* **Response:** rows live under **`data.items[]`** (not a bare list), one row
  per size (`chrtId`) per warehouse:
  ```json
  {"data": {"items": [
    {"nmId": 909379884, "chrtId": 936657114, "warehouseName": "Коледино",
     "regionName": "Центральный", "quantity": 1,
     "inWayToClient": 0, "inWayFromClient": 0}
  ]}}
  ```
  `chrtId` is the size characteristic id (no human-readable size label on this
  endpoint — that needs the content-cards API).
* **Ingestion mapping** → `monitoring.stock_snapshot`, one row per
  `(date, nm_id, warehouse_name, chrt_id)`: `quantity`, `in_way_to_client`,
  `in_way_from_client`, `region_name`. The snapshot date is the harvest's
  Moscow-time day. Total stock per SKU/day (sum over sizes+warehouses) drives
  OOS masking (§6); the size × warehouse grain powers the detail view.

## 6. Business Logic: Data Normalization (Baseline Organic Demand)
Raw metrics are volatile. To compute clean "Baseline Organic Demand" for A/B
tests and inventory forecasting, apply this per-SKU daily sequence
(implemented in `monitoring/services/normalization.py`):
1.  **Out of Stock (OOS) Masking:** for each day, sum stock across all
    warehouses. If total stock is 0, flag the day OOS and **exclude** it from
    baseline averages (do not record it as zero demand).
2.  **Promotional Lift Filtering:** cross-reference active price/promo calendars.
    * `Promo Cleaned Sales = Raw Sales / Promo Lift Factor`
3.  **Category Seasonality Adjustment:** apply weekly/monthly seasonality
    coefficients for the account category.
    * `Baseline Organic Demand = Promo Cleaned Sales / Seasonality Index`

> Promo-lift and seasonality inputs currently default to neutral (`1.0`); the
> daily funnel (§2) and stock (§5) feeds provide the raw sales and OOS signal
> the pipeline consumes today.
