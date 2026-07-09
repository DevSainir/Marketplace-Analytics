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

## 3. API: Sales Funnel — period aggregate (reference, not currently ingested)
* **Endpoint:** `POST /api/analytics/v3/sales-funnel/products`
* **Body:** `{"nmIDs": [...], "selectedPeriod": {"start", "end"}}` (uppercase
  `nmIDs` here).
* **Response:** `data.products[].statistic.{selected, past, comparison}` — each a
  period aggregate carrying `openCount/cartCount/orderCount/buyoutCount/
  addToWishlist` and a nested `conversions` object
  (`addToCartPercent/cartToOrderPercent/buyoutPercent`). Returns ~50 products
  per page (paginates via `isNextPage`/`offset`).
* Useful for at-a-glance period rollups; the daily endpoint (§2) is preferred
  because baseline-demand normalization needs per-day granularity.

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
