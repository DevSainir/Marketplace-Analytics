/**
 * Day-by-day metrics matrix for the monitoring table — a faithful replica of
 * the manager's Excel workbook.
 *
 * Every day is a section of columns (traffic type × display zone):
 *   Единая ставка (Поиск | Полки) · Руч. поиск (Поиск | Каталог) ·
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
 * Money is in the кабинет's settlement currency, which the backend states and
 * the caller passes in. The unit goes on the ROW label («Затраты, KGS») and the
 * cells stay bare numbers: a leaf column is ~52px, and «45 679 KGS» in it
 * would clip its leading digit and print a different number (see main.css).
 * «Каталог» is a legacy WB zone kept for workbook parity; it is always empty.
 */
import { formatMoney, formatNumber, formatPercent, moneyLabel } from '@/core/utils/format'

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
 * other cell (a derived rollup, a tainted split)
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
  { key: 'manual_search', zone: 'Поиск' },
  { key: 'manual_catalog', zone: 'Каталог' },
  { key: 'manual_shelves', zone: 'Полки', units: 2 },
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
 * Grid columns per day section — the colspan a whole day's cell needs.
 * «Руч. полки» is one bucket two grid columns wide (the room the unified
 * «Каталог» column left when it was removed), so this is not COLUMNS_PER_DAY.
 */
export const DAY_COLSPAN = TRAFFIC_COLUMNS.reduce((sum, column) => sum + (column.units ?? 1), 0)

/**
 * «Тип получения трафика» header groups (spans over TRAFFIC_COLUMNS).
 * `spansZones` groups have no zone split — their header cell spans the zones
 * row too instead of repeating the same word twice. `key` addresses the day's
 * campaign ids (`product.campaign_ids[iso][key]`) for the traffic-group links. «Руч. поиск» spans two
 * zones: WB search campaigns also deliver in каталог (backend-split).
 */
export const TRAFFIC_GROUPS = [
  { key: 'uni', label: 'Единая ставка', span: 2 },
  { key: 'manual_search', label: 'Руч. поиск', span: 2 },
  { key: 'manual_shelves', label: 'Руч. полки', span: 1, colspan: 2 },
  { key: 'cpc', label: 'CPC', span: 2 },
  { key: 'total', label: 'Общая', span: 1, spansZones: true },
  { key: 'organic', label: 'Органика', span: 1, spansZones: true },
]

/**
 * «ДРР от продаж» renders each campaign's zones as ONE merged cell (the value
 * is campaign-level — the backend repeats it on every zone bucket of the
 * group, so the first bucket carries the number). `offset` addresses the
 * group's first leaf cell within a day section; colspans sum to DAY_COLSPAN,
 * and the entries stay parallel to TRAFFIC_GROUPS (the phone list labels them
 * by position).
 */
export const DRR_SALES_COLUMNS = [
  { key: 'uni_search', span: 2, colspan: 2, offset: 0 },
  { key: 'manual_search', span: 2, colspan: 2, offset: 2 },
  { key: 'manual_shelves', span: 1, colspan: 2, offset: 4 },
  { key: 'cpc_search', span: 2, colspan: 2, offset: 5 },
  { key: 'total', span: 1, colspan: 1, offset: 7 },
  { key: 'organic', span: 1, colspan: 1, offset: 8 },
]

/**
 * «Процент выкупа» is ONE number for the whole day — a SKU-level lagged cohort
 * window, not a per-zone fact — so its row renders as a single cell spanning
 * the day's whole section. The value lives in the «Общая» bucket (offset 7).
 */
export const DAY_SPAN_COLUMNS = [
  { key: 'total', span: COLUMNS_PER_DAY, colspan: DAY_COLSPAN, offset: 7 },
]

/** "2026-07-05" -> "05.07.2026" for the day-section header. */
function dayLabel(iso) {
  const [year, month, day] = iso.split('-')
  return `${day}.${month}.${year}`
}

const fmtNumber = (v) => (v == null ? EMPTY : formatNumber(Math.round(v)))
const fmtMoney = (v) => (v == null ? EMPTY : formatMoney(v))
// Tenths for small per-click money (CPC): a click costs single units.
const fmtMoneyTenths = (v) => (v == null ? EMPTY : formatMoney(v, '', 1))
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
 * `money` rows take the кабинет's currency on their label (`moneyLabel`). The
 * funnel's counts say «шт» so that, with the currency unknown, «Заказы» the
 * count and «Заказы» the sum are still two different rows.
 *
 * `emphasis` renders the row bigger and bolder («ДРР от продаж» is the
 * headline efficiency number).
 */
const METRIC_DEFS = [
  { key: 'traffic_share', label: 'Доля трафика, %', group: 'traffic', format: fmtPercent },
  {
    key: 'spend',
    label: 'Затраты',
    money: true,
    tone: 'positive',
    group: 'traffic',
    format: fmtMoney,
  },
  { key: 'views', label: 'Показы', group: 'traffic', format: fmtNumber },
  { key: 'ctr', label: 'CTR, %', group: 'traffic', format: fmtPercent },
  { key: 'cpm', label: 'CPM', money: true, group: 'traffic', format: fmtMoney },
  { key: 'cpc', label: 'CPC', money: true, group: 'traffic', format: fmtMoneyTenths },
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
  { key: 'order_sum', label: 'Заказы', money: true, group: 'money', format: fmtMoney },
  { key: 'buyout_sum', label: 'Выкупы', money: true, group: 'money', format: fmtMoney },
  {
    key: 'cost_per_order',
    label: 'Стоимость заказа',
    money: true,
    group: 'money',
    format: fmtMoney,
  },
  {
    key: 'cost_per_cart',
    label: 'Стоимость корзины',
    money: true,
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
  { key: 'seller_price', label: 'Цена продавца', money: true, format: fmtMoney },
  { key: 'customer_price', label: 'Цена покупателя', money: true, format: fmtMoney },
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

/** A row's label as the table prints it: money rows carry the currency. */
function rowLabel(def, currency) {
  return def.money ? moneyLabel(def.label, currency) : def.label
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
 * @param {string} [currency] The кабинет's settlement currency; `''` while
 *   unknown, which leaves the money labels without a unit.
 * @returns {{days: Array<{iso: string, label: string}>, currency: string, rows: Array<{
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
 * Cell display string. The value comes precomputed from the backend — this is
 * formatting only.
 */
function cellDisplay(def, raw) {
  return def.format(raw)
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
function buildTotalRows(defs, matrix, backendValues, currency) {
  const totalIndex = matrix.buckets.indexOf('total')
  return defs.map((def) => {
    const values = backendValues.get(def.key)
    return {
      key: def.key,
      label: rowLabel(def, currency),
      tone: def.tone ?? null,
      cells: matrix.days.map((iso, dayIndex) => {
        const raw = resolveRaw(values, matrix.buckets.length, totalIndex, dayIndex)
        return {
          display: def.format(raw),
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

export function buildMetricsMatrix(product, currency = '') {
  const matrix = product?.matrix
  if (!matrix?.days?.length)
    return { days: [], rows: [], priceRows: [], stockRows: [], stockTotalRows: [], currency }

  const { backendValues, bucketCount, bucketIndexByColumn } = matrixLookups(matrix)
  const breakdowns = breakdownIndex(product)

  const rows = METRIC_DEFS.map((def) => {
    const values = backendValues.get(def.key)
    const skuValues = def.skuKey ? backendValues.get(def.skuKey) : null
    return {
      key: def.key,
      label: rowLabel(def, currency),
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
            display: cellDisplay(def, raw),
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
    priceRows: buildTotalRows(PRICE_METRIC_DEFS, matrix, backendValues, currency),
    stockRows: buildTotalRows(STOCK_METRIC_DEFS, matrix, backendValues, currency),
    stockTotalRows: buildTotalRows(STOCK_TOTAL_METRIC_DEFS, matrix, backendValues, currency),
    // The chart below the table reads the unit from here, so the two agree.
    currency,
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
 *   caller must rebuild from scratch (e.g. the window changed, or the currency
 *   arrived after the table was built — the labels would keep the old unit).
 */
export function patchMetricsMatrix(view, product, currency = '') {
  const matrix = product?.matrix
  if (!matrix?.days?.length || view?.days?.length !== matrix.days.length) return false
  if ((view.currency ?? '') !== currency) return false
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
        const display = cellDisplay(def, raw)
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
        if (cell.display !== display) cell.display = display
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
        const display = def.format(raw)
        const editable = isEditable('total', def.key)
        if (cell.raw !== raw) cell.raw = raw
        if (cell.display !== display) cell.display = display
        if (cell.editable !== editable) cell.editable = editable
      }
    }
  }

  return true
}
