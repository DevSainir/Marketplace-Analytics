/**
 * Day-by-day metrics matrix for the monitoring table — a faithful replica of
 * the manager's Excel workbook.
 *
 * Every day is a section of columns (traffic type × display zone):
 *   Единая ставка (Поиск | Полки | Каталог) · Руч. поиск (Поиск | Каталог) ·
 *   Руч. полки (Полки) · CPC (Поиск | Полки) · Общая · Органика
 * with the date spanning the section; sections flow horizontally, the newest
 * day on the right. Metric rows mirror the workbook's order.
 *
 * «CPC» is the pay-per-click campaign group: WB bills it per click instead of
 * per 1000 показов, so its ставка and its CPM cannot be read against the CPM
 * columns beside it and it gets a group of its own.
 *
 * ALL values arrive precomputed from the backend (`SkuDetailResponse.matrix`,
 * built by `services/matrix.py`) — strict rule: no calculations in the
 * frontend. This module only maps backend cells onto the workbook layout and
 * applies ru-RU display formatting; `null` cells render as «—».
 *
 * Money is in TWO units, and each row carries its own (`money: 'prices'|'ads'`).
 * A кабинет settled in KGS is still priced in RUB — so the prices and every sum
 * valued at them («Заказы», «Выкупы») are RUB — while its spend is in whatever
 * each campaign bills in: RUB before WB moved the ad account on 2026-08-20, KGS
 * after, both across that day. The backend states both on the detail response
 * (`price_currency`, `ad_currencies`); see {@link unitsOf}. Every money cell
 * carries its own sign («45 679с», «4 120₽») as `unit` beside its `figure`, so
 * the grid can let the sign give way before a digit in a ~52px leaf column —
 * a right-aligned overflow clips the LEADING glyph and would print a different
 * number (see main.css and `MatrixMetricsRows.vue`).
 * «Каталог» is a legacy WB zone kept for workbook parity; it is always empty.
 */
import { currencySign, formatMoneyFigure, formatNumber, formatPercent } from '@/core/utils/format'
import { campaignIdsByDay } from '@/modules/monitoring/campaignLinks'

// Missing values render as BLANK cells (was an em dash — the dashes read as
// noise across a mostly-empty ribbon).
const EMPTY = ''

/**
 * Which (bucket, metric) cells the manager may edit — presentation config, not
 * math (the backend owns every formula and rejects read-only edits anyway).
 * Mirrors the backend editability map: input cells are set directly; derived
 * cells back-solve one input server-side. Cells absent here are read-only.
 *
 * A cell is editable whenever its map entry is true — INCLUDING blank cells:
 * clicking a blank input cell lets the manager fill in a value the harvest
 * lacked (e.g. a missing price, or a count on a day WB has not served yet).
 * The backend still validates on commit — a blank cell with no input to attach
 * to (an ad bucket that never delivered) is rejected there, not hidden here.
 */
/**
 * Whether a (bucket, metric) cell is editable — EVERY cell is. Invertible
 * input cells back-solve their fact server-side (dynamic recompute); every
 * other cell (a derived rollup, the empty «Каталог» zone, a tainted split)
 * takes a display override there. The backend owns the routing; the frontend
 * just lets the manager click any cell. `bucket`/`metric` are kept for a
 * future per-cell lock and to mirror the call sites.
 */
function isEditable(bucket, metric) {
  return Boolean(bucket && metric)
}

/** Leaf columns of one day section, left to right. `key` = backend bucket. */
export const TRAFFIC_COLUMNS = [
  { key: 'uni_search', zone: 'Поиск' },
  { key: 'uni_shelves', zone: 'Полки' },
  { key: 'uni_catalog', zone: 'Каталог' },
  { key: 'manual_search', zone: 'Поиск' },
  { key: 'manual_catalog', zone: 'Каталог' },
  { key: 'manual_shelves', zone: 'Полки' },
  { key: 'cpc_search', zone: 'Поиск' },
  { key: 'cpc_shelves', zone: 'Полки' },
  { key: 'total', zone: 'Общая' },
  { key: 'organic', zone: 'Органика' },
]

/**
 * Leaf columns per day section — the stride of every `row.cells` index, and
 * the colspan a whole day's cell needs. Exported so the table's own rows
 * («Цены», the day note, «Действия») span the section without restating the
 * number: they got out of step with TRAFFIC_COLUMNS once already.
 */
export const COLUMNS_PER_DAY = TRAFFIC_COLUMNS.length

/**
 * «Тип получения трафика» header groups (spans over TRAFFIC_COLUMNS).
 * `spansZones` groups have no zone split — their header cell spans the zones
 * row too instead of repeating the same word twice. `key` names the group's
 * campaign in `campaigns.byDay` (see `campaignLinks.js`). «Руч. поиск» spans two
 * zones: WB search campaigns also deliver in каталог (backend-split).
 */
export const TRAFFIC_GROUPS = [
  { key: 'uni', label: 'Единая ставка', span: 3 },
  { key: 'manual_search', label: 'Руч. поиск', span: 2 },
  { key: 'manual_shelves', label: 'Руч. полки', span: 1 },
  { key: 'cpc', label: 'CPC', span: 2 },
  { key: 'total', label: 'Общая', span: 1, spansZones: true },
  { key: 'organic', label: 'Органика', span: 1, spansZones: true },
]

/**
 * «ДРР от продаж» renders each campaign's zones as ONE merged cell (the value
 * is campaign-level — the backend repeats it on every zone bucket of the
 * group, so the first bucket carries the number). `offset` addresses the
 * group's first leaf cell within a day section; spans sum to COLUMNS_PER_DAY,
 * and the entries stay parallel to TRAFFIC_GROUPS (the phone list labels them
 * by position).
 */
export const DRR_SALES_COLUMNS = [
  { key: 'uni_search', span: 3, offset: 0 },
  { key: 'manual_search', span: 2, offset: 3 },
  { key: 'manual_shelves', span: 1, offset: 5 },
  { key: 'cpc_search', span: 2, offset: 6 },
  { key: 'total', span: 1, offset: 8 },
  { key: 'organic', span: 1, offset: 9 },
]

/**
 * «Процент выкупа» is ONE number for the whole day — a SKU-level lagged cohort
 * window, not a per-zone fact — so its row renders as a single cell spanning
 * the day's whole section. The value lives in the «Общая» bucket (offset 8).
 */
export const DAY_SPAN_COLUMNS = [{ key: 'total', span: COLUMNS_PER_DAY, offset: 8 }]

/** "2026-07-05" -> "05.07.2026" for the day-section header. */
function dayLabel(iso) {
  const [year, month, day] = iso.split('-')
  return `${day}.${month}.${year}`
}

const fmtNumber = (v) => (v == null ? EMPTY : formatNumber(Math.round(v)))
const fmtMoney = (v) => (v == null ? EMPTY : formatMoneyFigure(v))
// Tenths for small per-click money (CPC): a click costs single units.
const fmtMoneyTenths = (v) => (v == null ? EMPTY : formatMoneyFigure(v, 1))
const fmtPercent = (v) => (v == null ? EMPTY : formatPercent(v))

/**
 * Metric rows in the workbook's order — presentation only (label, accent
 * tone, formatter). `key` matches the backend's `MATRIX_METRIC_KEYS`.
 *
 * `group` assigns each row to one of the four data blocks; every block gets
 * its own subtle row tint (see the `matrix-group--*` rules in main.css):
 * traffic (Доля трафика..Клики), funnel (Корзины..Конверсия в заказ),
 * money (Заказы..Стоимость корзины), efficiency (the ДРР/выкуп trio).
 *
 * `money` names where a money row's currency comes from — `'prices'` for the
 * prices and the sums valued at them, `'ads'` for spend and every cost built on
 * it — and each of its cells carries that currency's sign. The funnel's counts
 * say «шт» so that «Заказы» the count and «Заказы» the sum read apart.
 *
 * `emphasis` renders the row bigger and bolder («ДРР от продаж» is the
 * headline efficiency number).
 */
const METRIC_DEFS = [
  { key: 'traffic_share', label: 'Доля трафика, %', group: 'traffic', format: fmtPercent },
  {
    key: 'spend',
    label: 'Затраты',
    money: 'ads',
    tone: 'positive',
    group: 'traffic',
    format: fmtMoney,
  },
  { key: 'views', label: 'Показы', group: 'traffic', format: fmtNumber },
  { key: 'ctr', label: 'CTR, %', group: 'traffic', format: fmtPercent },
  { key: 'cpm', label: 'CPM', money: 'ads', group: 'traffic', format: fmtMoney },
  { key: 'cpc', label: 'CPC', money: 'ads', group: 'traffic', format: fmtMoneyTenths },
  { key: 'clicks', label: 'Клики', group: 'traffic', format: fmtNumber },
  // The cell itself is the кампания's count. `skuKey` points at the backend's
  // row for the VIEWED card's share of it, which is emitted only when the two
  // differ — i.e. when associated size/colour variants converted. Hovering
  // then breaks the cell down per variant; `assocCountField` picks this
  // metric's count out of the shared per-variant rows.
  {
    key: 'carts',
    label: 'Корзины, шт',
    tone: 'carts',
    group: 'funnel',
    format: fmtNumber,
    skuKey: 'carts_sku',
    assocCountField: 'add_to_cart',
  },
  {
    key: 'cart_conversion',
    label: 'Конверсия в корзину, %',
    tone: 'carts',
    group: 'funnel',
    format: fmtPercent,
  },
  {
    key: 'orders',
    label: 'Заказы, шт',
    tone: 'warning',
    group: 'funnel',
    format: fmtNumber,
    skuKey: 'orders_sku',
    assocCountField: 'orders',
  },
  {
    key: 'order_conversion',
    label: 'Конверсия в заказ, %',
    tone: 'warning',
    group: 'funnel',
    format: fmtPercent,
  },
  { key: 'order_sum', label: 'Заказы', money: 'prices', group: 'money', format: fmtMoney },
  { key: 'buyout_sum', label: 'Выкупы', money: 'prices', group: 'money', format: fmtMoney },
  {
    key: 'cost_per_order',
    label: 'Стоимость заказа',
    money: 'ads',
    group: 'money',
    format: fmtMoney,
  },
  {
    key: 'cost_per_cart',
    label: 'Стоимость корзины',
    money: 'ads',
    group: 'money',
    format: fmtMoney,
  },
  { key: 'drr_orders', label: 'ДРР от заказов, %', group: 'efficiency', format: fmtPercent },
  {
    key: 'drr_sales',
    label: 'ДРР от продаж, %',
    group: 'efficiency',
    emphasis: true,
    format: fmtPercent,
  },
  { key: 'buyout_percent', label: 'Процент выкупа, %', group: 'efficiency', format: fmtPercent },
]

/**
 * Prices & stock render as compact DAY-BOUND blocks under the metric rows
 * («Цены» / «Остатки» cards inside each day section of the same table).
 * These metrics only ever have «Общая»-bucket values, so each block row
 * carries one cell per day (bucket fixed to `total`). Prices are editable
 * inputs (the «Заказы»/«Выкупы» sums and «СПП» derive from them); stock rows are
 * read-only snapshot facts.
 */
const PRICE_METRIC_DEFS = [
  { key: 'seller_price', label: 'Цена продавца', money: 'prices', format: fmtMoney },
  { key: 'customer_price', label: 'Цена покупателя', money: 'prices', format: fmtMoney },
  { key: 'spp', label: 'СПП, %', tone: 'positive', format: fmtPercent },
]
const STOCK_METRIC_DEFS = [
  { key: 'stock_quantity', label: 'Остаток, шт', format: fmtNumber },
  { key: 'stock_to_client', label: 'В пути к клиенту, шт', format: fmtNumber },
  { key: 'stock_from_client', label: 'В пути от клиента, шт', format: fmtNumber },
]
// The compact «Всего» card next to «Остатки»: остаток + оба «в пути»,
// COMPUTED BY THE BACKEND (`stock_total` matrix row) — mapped here like any
// other metric, label/formatting only.
const STOCK_TOTAL_METRIC_DEFS = [{ key: 'stock_total', label: 'Всего, шт', format: fmtNumber }]

/** Which unit each money metric is in, by backend metric key. */
const MONEY_SOURCE = new Map(
  [...METRIC_DEFS, ...PRICE_METRIC_DEFS]
    .filter((def) => def.money)
    .map((def) => [def.key, def.money]),
)

/**
 * The unit of one money METRIC — what the chart under the table names its
 * series and hover rows with, from the same map the table's labels use.
 *
 * @param {string} metric A backend metric key (`spend`, `order_sum`, …).
 * @param {{prices?: string, ads?: string[]}} [currencies]
 * @returns {string}
 */
export function unitOfMetric(metric, currencies = {}) {
  return moneyCurrency(MONEY_SOURCE.get(metric), currencies)
}

/**
 * The two units a SKU's money is in, as the detail response states them.
 *
 * @param {object} [product] A `SkuDetailResponse`.
 * @returns {{prices: string, ads: string[]}} `''`/`[]` while WB has named none.
 */
export function unitsOf(product) {
  return { prices: product?.price_currency ?? '', ads: product?.ad_currencies ?? [] }
}

/**
 * The currency of one money source: the prices' code, or the campaigns' codes —
 * both for a window holding campaigns from both sides of the 2026-08-20 switch.
 * Nothing is converted anywhere, so a sum of both carries both signs.
 *
 * @param {'prices'|'ads'|undefined} source
 * @param {{prices?: string, ads?: string[]}} [currencies]
 * @returns {string|string[]} What {@link currencySign} takes.
 */
export function moneyCurrency(source, currencies = {}) {
  if (source === 'ads') return currencies.ads ?? []
  if (source === 'prices') return currencies.prices ?? ''
  return ''
}

/** A row's label as the table prints it. The currency is on each cell, not here. */
function rowLabel(def) {
  return def.label
}

/**
 * Lay out the backend matrix of one `SkuDetailResponse` for the table.
 *
 * Row values are flat, in day-major order: for day index `d` and traffic
 * column index `c` (within TRAFFIC_COLUMNS) the cell lives at
 * `values[d * TRAFFIC_COLUMNS.length + c]`. Each cell is an object carrying the
 * formatted `display` string, the `raw` number (for editing), the addressing
 * (`day`/`bucket`/`metric`), and whether it is `editable`. The numbers were all
 * computed server-side — the frontend only formats and marks editability.
 *
 * @param {object} product A `SkuDetailResponse`.
 * @param {{prices?: string, ads?: string[]}} [currencies] The units of the
 *   prices and of the spend ({@link unitsOf}); unknown ones leave the money
 *   labels without a unit.
 * @returns {{days: Array<{iso: string, label: string}>, currencies: object, rows: Array<{
 *   key: string, label: string, tone: string|null,
 *   cells: Array<{display: string, raw: number|null, day: string,
 *     bucket: string, metric: string, editable: boolean}>}>}}
 */
/** Backend cell value for a metric row at (dayIndex, columnIndex), or null. */
function resolveRaw(values, bucketCount, bucketIndex, dayIndex) {
  if (bucketIndex === -1 || !values) return null
  return values[dayIndex * bucketCount + bucketIndex] ?? null
}

/**
 * A cell's printed parts: the `figure`, the currency sign as `unit` (money rows
 * only, and only when there is a figure), and `display`, the two together for
 * places with room — the phone list, the hover. The value comes precomputed
 * from the backend — this is formatting only.
 */
function cellParts(def, raw, currencies) {
  const figure = def.format(raw)
  const unit = def.money && raw != null ? currencySign(moneyCurrency(def.money, currencies)) : ''
  return { figure, unit, display: figure + unit }
}

/**
 * The hover payload of a carts/orders cell, or null when the cell has no
 * associative gap (nothing to break down — the campaign's whole count is the
 * viewed SKU's).
 *
 * `associated` is the ASSOCIATED share of the cell: the conversions the campaign
 * delivered that were booked on OTHER size/colour variants (the cell minus the
 * viewed SKU's own share). `skus` names every variant behind the cell — the
 * viewed one included and flagged, so the row it contributes is visible next to
 * the ones it did not; those rows sum to the cell, of which the unflagged ones
 * sum to `associated`. `exact` says whether the counts are harvested fact or the
 * backend's apportionment of a two-zone campaign (the tooltip captions it).
 */
function cellAssoc(def, raw, skuRaw, breakdown, viewedNmId) {
  if (skuRaw == null) return null
  const skus = (breakdown?.skus ?? [])
    .map((sku) => ({
      nm_id: sku.nm_id,
      vendor_code: sku.vendor_code,
      count: sku[def.assocCountField],
      // Which variant is the one on screen is a property of this page, not of
      // the harvested facts — so it is stamped here, not by the backend.
      isViewed: sku.nm_id === viewedNmId,
    }))
    // A variant that took orders but no carts belongs in the orders list only.
    .filter((sku) => sku.count > 0)
  return {
    associated: (raw ?? 0) - skuRaw,
    skus,
    exact: breakdown?.exact ?? true,
  }
}

/**
 * Index the base state's per-variant breakdowns by `"<day>:<bucket>"`.
 *
 * The display matrix carries numbers only, so the breakdown rides the editable
 * base (where it is a read-only fact, like the associative totals themselves).
 */
function breakdownIndex(product) {
  const index = new Map()
  for (const day of product?.matrix_base?.days ?? []) {
    for (const [bucket, base] of Object.entries(day.buckets ?? {})) {
      if (base.assoc_skus?.length) {
        index.set(`${day.day}:${bucket}`, { skus: base.assoc_skus, exact: base.assoc_exact })
      }
    }
  }
  return index
}

/** Per-matrix lookups shared by build + patch (bucket index per column, etc.). */
function matrixLookups(matrix) {
  return {
    backendValues: new Map(matrix.rows.map((row) => [row.key, row.values])),
    bucketCount: matrix.buckets.length,
    // Column order is presentation-owned; resolve each column to its backend
    // bucket index once (−1 = bucket unknown to this backend version -> «—»).
    bucketIndexByColumn: TRAFFIC_COLUMNS.map((column) => matrix.buckets.indexOf(column.key)),
  }
}

/** Build the «Общая»-only rows of one mini block (one cell per day). */
function buildTotalRows(defs, matrix, backendValues, currencies) {
  const totalIndex = matrix.buckets.indexOf('total')
  return defs.map((def) => {
    const values = backendValues.get(def.key)
    return {
      key: def.key,
      label: rowLabel(def),
      tone: def.tone ?? null,
      cells: matrix.days.map((iso, dayIndex) => {
        const raw = resolveRaw(values, matrix.buckets.length, totalIndex, dayIndex)
        return {
          ...cellParts(def, raw, currencies),
          raw,
          day: iso,
          bucket: 'total',
          metric: def.key,
          editable: isEditable('total', def.key),
        }
      }),
    }
  })
}

export function buildMetricsMatrix(product, currencies = {}) {
  const matrix = product?.matrix
  if (!matrix?.days?.length)
    return { days: [], rows: [], priceRows: [], stockRows: [], stockTotalRows: [], currencies }

  const { backendValues, bucketCount, bucketIndexByColumn } = matrixLookups(matrix)
  const breakdowns = breakdownIndex(product)

  const rows = METRIC_DEFS.map((def) => {
    const values = backendValues.get(def.key)
    const skuValues = def.skuKey ? backendValues.get(def.skuKey) : null
    return {
      key: def.key,
      label: rowLabel(def),
      tone: def.tone ?? null,
      group: def.group ?? null,
      emphasis: def.emphasis ?? false,
      cells: matrix.days.flatMap((iso, dayIndex) =>
        TRAFFIC_COLUMNS.map((column, columnIndex) => {
          const bucketIndex = bucketIndexByColumn[columnIndex]
          const raw = resolveRaw(values, bucketCount, bucketIndex, dayIndex)
          const skuRaw = skuValues
            ? resolveRaw(skuValues, bucketCount, bucketIndex, dayIndex)
            : null
          return {
            ...cellParts(def, raw, currencies),
            raw,
            assoc: cellAssoc(
              def,
              raw,
              skuRaw,
              breakdowns.get(`${iso}:${column.key}`),
              product.nm_id,
            ),
            day: iso,
            bucket: column.key,
            metric: def.key,
            editable: isEditable(column.key, def.key),
          }
        }),
      ),
    }
  })

  return {
    days: matrix.days.map((iso) => ({ iso, label: dayLabel(iso) })),
    rows,
    priceRows: buildTotalRows(PRICE_METRIC_DEFS, matrix, backendValues, currencies),
    stockRows: buildTotalRows(STOCK_METRIC_DEFS, matrix, backendValues, currencies),
    stockTotalRows: buildTotalRows(STOCK_TOTAL_METRIC_DEFS, matrix, backendValues, currencies),
    // The chart below the table reads the units from here, so the two agree.
    currencies,
    // The header's campaign links (`campaignLinks.js`): the SKU, and per day
    // which campaign each traffic group ran.
    campaigns: { nmId: product.nm_id, byDay: campaignIdsByDay(product.matrix_base) },
  }
}

/**
 * Patch an existing view's cells in place from a new backend matrix, writing
 * only the values that actually changed. This is the fast path for an edit /
 * undo / redo: the `days` and cell structure are unchanged (same window), so
 * mutating just the ~handful of affected cells lets Vue update only those DOM
 * nodes — no full re-render of the (potentially thousands of) cells.
 *
 * @returns {boolean} true when patched; false when the shape differs and the
 *   caller must rebuild from scratch (e.g. the window changed, or a unit
 *   arrived after the table was built — the labels would keep the old one).
 */
export function patchMetricsMatrix(view, product, currencies = {}) {
  const matrix = product?.matrix
  if (!matrix?.days?.length || view?.days?.length !== matrix.days.length) return false
  for (const source of ['prices', 'ads']) {
    const was = currencySign(moneyCurrency(source, view.currencies))
    if (was !== currencySign(moneyCurrency(source, currencies))) return false
  }
  if (view.rows.length !== METRIC_DEFS.length) return false
  if (view.priceRows?.length !== PRICE_METRIC_DEFS.length) return false
  if (view.stockRows?.length !== STOCK_METRIC_DEFS.length) return false
  if (view.stockTotalRows?.length !== STOCK_TOTAL_METRIC_DEFS.length) return false

  const { backendValues, bucketCount, bucketIndexByColumn } = matrixLookups(matrix)
  const defByKey = new Map(METRIC_DEFS.map((def) => [def.key, def]))
  const columnCount = TRAFFIC_COLUMNS.length
  const breakdowns = breakdownIndex(product)

  for (const row of view.rows) {
    const def = defByKey.get(row.key)
    if (!def) continue
    const values = backendValues.get(row.key)
    const skuValues = def.skuKey ? backendValues.get(def.skuKey) : null
    for (let dayIndex = 0; dayIndex < matrix.days.length; dayIndex += 1) {
      for (let columnIndex = 0; columnIndex < columnCount; columnIndex += 1) {
        const cell = row.cells[dayIndex * columnCount + columnIndex]
        const bucketIndex = bucketIndexByColumn[columnIndex]
        const raw = resolveRaw(values, bucketCount, bucketIndex, dayIndex)
        const skuRaw = skuValues ? resolveRaw(skuValues, bucketCount, bucketIndex, dayIndex) : null
        const parts = cellParts(def, raw, currencies)
        const editable = isEditable(TRAFFIC_COLUMNS[columnIndex].key, def.key)
        const assoc = cellAssoc(
          def,
          raw,
          skuRaw,
          breakdowns.get(`${cell.day}:${TRAFFIC_COLUMNS[columnIndex].key}`),
          product.nm_id,
        )
        // Assign only on change so untouched cells trigger no reactivity.
        if (cell.raw !== raw) cell.raw = raw
        assignParts(cell, parts)
        if (cell.editable !== editable) cell.editable = editable
        // An edit to the SKU's own slice moves the associated remainder with
        // it; compare by value, the object is rebuilt each patch.
        if (JSON.stringify(cell.assoc) !== JSON.stringify(assoc)) cell.assoc = assoc
      }
    }
  }

  // Mini blocks: one «Общая» cell per day.
  const totalIndex = matrix.buckets.indexOf('total')
  for (const [defs, rows] of [
    [PRICE_METRIC_DEFS, view.priceRows],
    [STOCK_METRIC_DEFS, view.stockRows],
    [STOCK_TOTAL_METRIC_DEFS, view.stockTotalRows],
  ]) {
    const miniDefByKey = new Map(defs.map((def) => [def.key, def]))
    for (const row of rows) {
      const def = miniDefByKey.get(row.key)
      if (!def) continue
      const values = backendValues.get(row.key)
      for (let dayIndex = 0; dayIndex < matrix.days.length; dayIndex += 1) {
        const cell = row.cells[dayIndex]
        const raw = resolveRaw(values, bucketCount, totalIndex, dayIndex)
        const editable = isEditable('total', def.key)
        if (cell.raw !== raw) cell.raw = raw
        assignParts(cell, cellParts(def, raw, currencies))
        if (cell.editable !== editable) cell.editable = editable
      }
    }
  }

  return true
}

/** Write a cell's printed parts, touching only what changed (no idle reactivity). */
function assignParts(cell, parts) {
  if (cell.figure !== parts.figure) cell.figure = parts.figure
  if (cell.unit !== parts.unit) cell.unit = parts.unit
  if (cell.display !== parts.display) cell.display = parts.display
}
