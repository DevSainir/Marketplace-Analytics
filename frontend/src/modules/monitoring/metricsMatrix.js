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
import { formatCurrency, formatNumber, formatPercent } from '@/core/utils/format'

const EM_DASH = '—'

/**
 * Which (bucket, metric) cells the manager may edit — presentation config, not
 * math (the backend owns every formula and rejects read-only edits anyway).
 * Mirrors the backend editability map: input cells are set directly; derived
 * cells back-solve one input server-side. Cells absent here are read-only.
 *
 * A cell is only actually editable when its map entry is true AND its value is
 * a real number (an «—» cell has nothing to edit).
 */
const AD_EDITABLE = new Set([
  'views',
  'clicks',
  'carts',
  'spend',
  'orders',
  'order_sum',
  'ctr',
  'cpm',
  'cpc',
  'cart_conversion',
  'order_conversion',
  'cost_per_order',
  'cost_per_cart',
  'drr_orders',
  'traffic_share',
])
const TOTAL_EDITABLE = new Set([
  'clicks',
  'carts',
  'orders',
  // order_sum / buyout_sum / spp are derived from the prices (read-only); the
  // prices themselves are the editable inputs.
  'seller_price',
  'customer_price',
  'cart_conversion',
  'order_conversion',
])
const ORGANIC_EDITABLE = new Set(['clicks', 'carts', 'orders'])
const AD_BUCKETS = new Set(['uni_search', 'uni_shelves', 'manual_search', 'manual_shelves'])

/** Whether a (bucket, metric) pair is editable in principle (ignores value). */
function isEditable(bucket, metric) {
  if (AD_BUCKETS.has(bucket)) return AD_EDITABLE.has(metric)
  if (bucket === 'total') return TOTAL_EDITABLE.has(metric)
  if (bucket === 'organic') return ORGANIC_EDITABLE.has(metric)
  return false // uni_catalog and anything else
}

/** Leaf columns of one day section, left to right. `key` = backend bucket. */
export const TRAFFIC_COLUMNS = [
  { key: 'uni_search', zone: 'Поиск' },
  { key: 'uni_shelves', zone: 'Полки' },
  { key: 'uni_catalog', zone: 'Каталог' },
  { key: 'manual_search', zone: 'Поиск' },
  { key: 'manual_shelves', zone: 'Полки' },
  { key: 'total', zone: 'Общая' },
  { key: 'organic', zone: 'Органика' },
]

/**
 * «Тип получения трафика» header groups (spans over TRAFFIC_COLUMNS).
 * `spansZones` groups have no zone split — their header cell spans the zones
 * row too instead of repeating the same word twice.
 */
export const TRAFFIC_GROUPS = [
  { label: 'Единая ставка', span: 3 },
  { label: 'Руч. поиск', span: 1 },
  { label: 'Руч. полки', span: 1 },
  { label: 'Общая', span: 1, spansZones: true },
  { label: 'Органика', span: 1, spansZones: true },
]

/** "2026-07-05" -> "05.07.2026" for the day-section header. */
function dayLabel(iso) {
  const [year, month, day] = iso.split('-')
  return `${day}.${month}.${year}`
}

const fmtNumber = (v) => (v == null ? EM_DASH : formatNumber(Math.round(v)))
const fmtCurrency = (v) => (v == null ? EM_DASH : formatCurrency(v))
const fmtPercent = (v) => (v == null ? EM_DASH : formatPercent(v))

/**
 * Metric rows in the workbook's order — presentation only (label, accent
 * tone, formatter). `key` matches the backend's `MATRIX_METRIC_KEYS`.
 *
 * `group` clusters rows between thick horizontal dividers (money economics
 * vs ДРР/выкуп efficiency) — separation only, no tinting.
 */
const METRIC_DEFS = [
  { key: 'traffic_share', label: 'Доля трафика, %', format: fmtPercent },
  { key: 'spend', label: 'Затраты, ₽', tone: 'negative', format: fmtCurrency },
  { key: 'views', label: 'Показы', format: fmtNumber },
  { key: 'ctr', label: 'CTR, %', format: fmtPercent },
  { key: 'cpm', label: 'CPM, ₽', format: fmtCurrency },
  { key: 'cpc', label: 'CPC, ₽', format: fmtCurrency },
  { key: 'clicks', label: 'Клики', format: fmtNumber },
  { key: 'carts', label: 'Корзины', tone: 'carts', format: fmtNumber },
  { key: 'cart_conversion', label: 'Конверсия в корзину, %', tone: 'carts', format: fmtPercent },
  { key: 'orders', label: 'Заказы', tone: 'positive', format: fmtNumber },
  {
    key: 'order_conversion',
    label: 'Конверсия в заказ, %',
    tone: 'positive',
    format: fmtPercent,
  },
  { key: 'order_sum', label: 'Заказы, ₽', group: 'orders', format: fmtCurrency },
  { key: 'buyout_sum', label: 'Выкупы, ₽', group: 'orders', format: fmtCurrency },
  { key: 'cost_per_order', label: 'Стоимость заказа, ₽', group: 'orders', format: fmtCurrency },
  { key: 'cost_per_cart', label: 'Стоимость корзины, ₽', group: 'orders', format: fmtCurrency },
  { key: 'drr_orders', label: 'ДРР от заказов, %', group: 'drr', format: fmtPercent },
  { key: 'drr_sales', label: 'ДРР от продаж, %', group: 'drr', format: fmtPercent },
  { key: 'buyout_percent', label: 'Процент выкупа, %', group: 'drr', format: fmtPercent },
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
          editable: raw != null && isEditable('total', def.key),
        }
      }),
    }
  })
}

export function buildMetricsMatrix(product) {
  const matrix = product?.matrix
  if (!matrix?.days?.length) return { days: [], rows: [], priceRows: [], stockRows: [] }

  const { backendValues, bucketCount, bucketIndexByColumn } = matrixLookups(matrix)

  const rows = METRIC_DEFS.map((def) => {
    const values = backendValues.get(def.key)
    return {
      key: def.key,
      label: def.label,
      tone: def.tone ?? null,
      group: def.group ?? null,
      cells: matrix.days.flatMap((iso, dayIndex) =>
        TRAFFIC_COLUMNS.map((column, columnIndex) => {
          const raw = resolveRaw(values, bucketCount, bucketIndexByColumn[columnIndex], dayIndex)
          return {
            display: def.format(raw),
            raw,
            day: iso,
            bucket: column.key,
            metric: def.key,
            editable: raw != null && isEditable(column.key, def.key),
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

  const { backendValues, bucketCount, bucketIndexByColumn } = matrixLookups(matrix)
  const defByKey = new Map(METRIC_DEFS.map((def) => [def.key, def]))
  const columnCount = TRAFFIC_COLUMNS.length

  for (const row of view.rows) {
    const def = defByKey.get(row.key)
    if (!def) continue
    const values = backendValues.get(row.key)
    for (let dayIndex = 0; dayIndex < matrix.days.length; dayIndex += 1) {
      for (let columnIndex = 0; columnIndex < columnCount; columnIndex += 1) {
        const cell = row.cells[dayIndex * columnCount + columnIndex]
        const raw = resolveRaw(values, bucketCount, bucketIndexByColumn[columnIndex], dayIndex)
        const display = def.format(raw)
        const editable = raw != null && isEditable(TRAFFIC_COLUMNS[columnIndex].key, def.key)
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
        const editable = raw != null && isEditable('total', def.key)
        if (cell.raw !== raw) cell.raw = raw
        if (cell.display !== display) cell.display = display
        if (cell.editable !== editable) cell.editable = editable
      }
    }
  }
  return true
}
