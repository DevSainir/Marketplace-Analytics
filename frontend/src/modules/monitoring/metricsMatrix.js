/**
 * Day-by-day metrics matrix for the monitoring table — a faithful replica of
 * the manager's Excel workbook.
 *
 * Every day is a section of 7 columns (traffic type × display zone):
 *   Единая ставка (Поиск | Полки | Каталог) · Руч. поиск (Поиск) ·
 *   Руч. полки (Полки) · Общая · Органика
 * with the date spanning the section; sections flow horizontally, the newest
 * day on the right. Metric rows mirror the workbook's order.
 *
 * ALL values arrive precomputed from the backend (`SkuDetailResponse.matrix`,
 * built by `services/matrix.py`) — strict rule: no calculations in the
 * frontend. This module only maps backend cells onto the workbook layout and
 * applies ru-RU display formatting; `null` cells render as «—».
 * «Каталог» is a legacy WB zone kept for workbook parity; it is always empty.
 */
import {
  formatCurrency,
  formatCurrencyTenths,
  formatNumber,
  formatPercent,
} from '@/core/utils/format'

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
  { key: 'total', zone: 'Общая' },
  { key: 'organic', zone: 'Органика' },
]

/**
 * «Тип получения трафика» header groups (spans over TRAFFIC_COLUMNS).
 * `spansZones` groups have no zone split — their header cell spans the zones
 * row too instead of repeating the same word twice. «Руч. поиск» spans two
 * zones: WB search campaigns also deliver in каталог (backend-split).
 */
export const TRAFFIC_GROUPS = [
  { label: 'Единая ставка', span: 3 },
  { label: 'Руч. поиск', span: 2 },
  { label: 'Руч. полки', span: 1 },
  { label: 'Общая', span: 1, spansZones: true },
  { label: 'Органика', span: 1, spansZones: true },
]

/** "2026-07-05" -> "05.07.2026" for the day-section header. */
function dayLabel(iso) {
  const [year, month, day] = iso.split('-')
  return `${day}.${month}.${year}`
}

const fmtNumber = (v) => (v == null ? EMPTY : formatNumber(Math.round(v)))
const fmtCurrency = (v) => (v == null ? EMPTY : formatCurrency(v))
const fmtCurrencyTenths = (v) => (v == null ? EMPTY : formatCurrencyTenths(v))
const fmtPercent = (v) => (v == null ? EMPTY : formatPercent(v))

/**
 * Metric rows in the workbook's order — presentation only (label, accent
 * tone, formatter). `key` matches the backend's `MATRIX_METRIC_KEYS`.
 *
 * `group` assigns each row to one of the four data blocks; every block gets
 * its own subtle row tint (see the `matrix-group--*` rules in main.css):
 * traffic (Доля трафика..Клики), funnel (Корзины..Конверсия в заказ),
 * money (Заказы, ₽..Стоимость корзины), efficiency (the ДРР/выкуп trio).
 *
 * `emphasis` renders the row bigger and bolder («ДРР от продаж» is the
 * headline efficiency number).
 */
const METRIC_DEFS = [
  { key: 'traffic_share', label: 'Доля трафика, %', group: 'traffic', format: fmtPercent },
  { key: 'spend', label: 'Затраты, ₽', tone: 'positive', group: 'traffic', format: fmtCurrency },
  { key: 'views', label: 'Показы', group: 'traffic', format: fmtNumber },
  { key: 'ctr', label: 'CTR, %', group: 'traffic', format: fmtPercent },
  { key: 'cpm', label: 'CPM, ₽', group: 'traffic', format: fmtCurrency },
  { key: 'cpc', label: 'CPC, ₽', group: 'traffic', format: fmtCurrencyTenths },
  { key: 'clicks', label: 'Клики', group: 'traffic', format: fmtNumber },
  // `assocKey` points at the backend's associative-conversion row (campaign
  // totals including associated size/colour variants). When that row has a
  // value for the cell, the cell renders as «100(71)» — total(this SKU).
  {
    key: 'carts',
    label: 'Корзины',
    tone: 'carts',
    group: 'funnel',
    format: fmtNumber,
    assocKey: 'carts_assoc',
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
    label: 'Заказы',
    tone: 'warning',
    group: 'funnel',
    format: fmtNumber,
    assocKey: 'orders_assoc',
  },
  {
    key: 'order_conversion',
    label: 'Конверсия в заказ, %',
    tone: 'warning',
    group: 'funnel',
    format: fmtPercent,
  },
  { key: 'order_sum', label: 'Заказы, ₽', group: 'money', format: fmtCurrency },
  { key: 'buyout_sum', label: 'Выкупы, ₽', group: 'money', format: fmtCurrency },
  { key: 'cost_per_order', label: 'Стоимость заказа, ₽', group: 'money', format: fmtCurrency },
  { key: 'cost_per_cart', label: 'Стоимость корзины, ₽', group: 'money', format: fmtCurrency },
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
 * inputs («Заказы/Выкупы ₽» and «СПП» derive from them); stock rows are
 * read-only snapshot facts.
 */
const PRICE_METRIC_DEFS = [
  { key: 'seller_price', label: 'Цена продавца, ₽', format: fmtCurrency },
  { key: 'customer_price', label: 'Цена покупателя, ₽', format: fmtCurrency },
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
 * @returns {{days: Array<{iso: string, label: string}>, rows: Array<{
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
 * Cell display string: the associative decoration «100(71)» when the backend
 * emitted an all-variant total for the cell, the plain formatted value
 * otherwise. Both numbers come precomputed from the backend — this is
 * formatting only.
 */
function cellDisplay(def, raw, assocRaw) {
  if (assocRaw == null) return def.format(raw)
  return `${def.format(assocRaw)}(${def.format(raw)})`
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
function buildTotalRows(defs, matrix, backendValues) {
  const totalIndex = matrix.buckets.indexOf('total')
  return defs.map((def) => {
    const values = backendValues.get(def.key)
    return {
      key: def.key,
      label: def.label,
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

export function buildMetricsMatrix(product) {
  const matrix = product?.matrix
  if (!matrix?.days?.length)
    return { days: [], rows: [], priceRows: [], stockRows: [], stockTotalRows: [] }

  const { backendValues, bucketCount, bucketIndexByColumn } = matrixLookups(matrix)

  const rows = METRIC_DEFS.map((def) => {
    const values = backendValues.get(def.key)
    const assocValues = def.assocKey ? backendValues.get(def.assocKey) : null
    return {
      key: def.key,
      label: def.label,
      tone: def.tone ?? null,
      group: def.group ?? null,
      emphasis: def.emphasis ?? false,
      cells: matrix.days.flatMap((iso, dayIndex) =>
        TRAFFIC_COLUMNS.map((column, columnIndex) => {
          const bucketIndex = bucketIndexByColumn[columnIndex]
          const raw = resolveRaw(values, bucketCount, bucketIndex, dayIndex)
          const assocRaw = assocValues
            ? resolveRaw(assocValues, bucketCount, bucketIndex, dayIndex)
            : null
          return {
            display: cellDisplay(def, raw, assocRaw),
            raw,
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
    priceRows: buildTotalRows(PRICE_METRIC_DEFS, matrix, backendValues),
    stockRows: buildTotalRows(STOCK_METRIC_DEFS, matrix, backendValues),
    stockTotalRows: buildTotalRows(STOCK_TOTAL_METRIC_DEFS, matrix, backendValues),
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
 *   caller must rebuild from scratch (e.g. the window changed).
 */
export function patchMetricsMatrix(view, product) {
  const matrix = product?.matrix
  if (!matrix?.days?.length || view?.days?.length !== matrix.days.length) return false
  if (view.rows.length !== METRIC_DEFS.length) return false
  if (view.priceRows?.length !== PRICE_METRIC_DEFS.length) return false
  if (view.stockRows?.length !== STOCK_METRIC_DEFS.length) return false
  if (view.stockTotalRows?.length !== STOCK_TOTAL_METRIC_DEFS.length) return false

  const { backendValues, bucketCount, bucketIndexByColumn } = matrixLookups(matrix)
  const defByKey = new Map(METRIC_DEFS.map((def) => [def.key, def]))
  const columnCount = TRAFFIC_COLUMNS.length

  for (const row of view.rows) {
    const def = defByKey.get(row.key)
    if (!def) continue
    const values = backendValues.get(row.key)
    const assocValues = def.assocKey ? backendValues.get(def.assocKey) : null
    for (let dayIndex = 0; dayIndex < matrix.days.length; dayIndex += 1) {
      for (let columnIndex = 0; columnIndex < columnCount; columnIndex += 1) {
        const cell = row.cells[dayIndex * columnCount + columnIndex]
        const bucketIndex = bucketIndexByColumn[columnIndex]
        const raw = resolveRaw(values, bucketCount, bucketIndex, dayIndex)
        const assocRaw = assocValues
          ? resolveRaw(assocValues, bucketCount, bucketIndex, dayIndex)
          : null
        const display = cellDisplay(def, raw, assocRaw)
        const editable = isEditable(TRAFFIC_COLUMNS[columnIndex].key, def.key)
        // Assign only on change so untouched cells trigger no reactivity.
        if (cell.raw !== raw) cell.raw = raw
        if (cell.display !== display) cell.display = display
        if (cell.editable !== editable) cell.editable = editable
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
