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
 * Currently populated: «Общая» (funnel + cross-campaign ad totals) and
 * «Органика» (общая − реклама). The per-type/zone columns stay empty until
 * campaign placements (WB `/adverts` bid_type + placements) are ingested.
 *
 * Pure functions only — no store, no fetching — so the table stays dumb and
 * the math stays unit-testable.
 */
import { formatCurrency, formatNumber, formatPercent } from '@/core/utils/format'

const EM_DASH = '—'

/** Leaf columns of one day section, left to right. */
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

/** Inclusive ISO date sequence start..end (UTC math: no DST surprises). */
export function isoDateRange(startIso, endIso) {
  const start = new Date(`${startIso}T00:00:00Z`)
  const end = new Date(`${endIso}T00:00:00Z`)
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime()) || start > end) return []
  const days = []
  for (let t = start.getTime(); t <= end.getTime(); t += 86_400_000) {
    days.push(new Date(t).toISOString().slice(0, 10))
  }
  return days
}

/** "2026-07-05" -> "05.07.2026" for the day-section header. */
function dayLabel(iso) {
  const [year, month, day] = iso.split('-')
  return `${day}.${month}.${year}`
}

/** Numerator / denominator, or null when it cannot be computed (÷0 → «—»). */
function ratio(numerator, denominator) {
  if (numerator == null || !denominator) return null
  return numerator / denominator
}

const fmtNumber = (v) => (v == null ? EM_DASH : formatNumber(Math.round(v)))
const fmtCurrency = (v) => (v == null ? EM_DASH : formatCurrency(v))
const fmtPercent = (v) => (v == null ? EM_DASH : formatPercent(v))

/**
 * Metric rows in the workbook's order. `total`/`organic` compute the two
 * columns we have data for; the per-type/zone columns render «—» until
 * campaign placements are ingested. Formulas follow the workbook: «Клики
 * (Общая)» are card opens, «Органика» = Общая − реклама, CTR/CPM have no
 * «Общая» value (mixed zones), CPC (Общая) = затраты / рекламные клики.
 */
const METRIC_DEFS = [
  { key: 'traffic_share', label: 'Доля трафика, %', format: fmtPercent },
  {
    key: 'spend',
    label: 'Затраты, ₽',
    tone: 'warning',
    format: fmtCurrency,
    total: (f, a) => a?.spend ?? null,
  },
  { key: 'views', label: 'Показы', format: fmtNumber, total: (f, a) => a?.views ?? null },
  { key: 'ctr', label: 'CTR, %', format: fmtPercent },
  { key: 'cpm', label: 'CPM, ₽', format: fmtCurrency },
  {
    key: 'cpc',
    label: 'CPC, ₽',
    format: fmtCurrency,
    total: (f, a) => ratio(a?.spend, a?.clicks),
  },
  {
    key: 'clicks',
    label: 'Клики',
    format: fmtNumber,
    total: (f) => f?.open_count ?? null,
    organic: (f, a) => (f == null ? null : f.open_count - (a?.clicks ?? 0)),
  },
  {
    key: 'carts',
    label: 'Корзины',
    tone: 'carts',
    format: fmtNumber,
    total: (f) => f?.cart_count ?? null,
    organic: (f, a) => (f == null ? null : f.cart_count - (a?.add_to_cart ?? 0)),
  },
  {
    key: 'cart_conversion',
    label: 'Конверсия в корзину, %',
    tone: 'carts',
    format: fmtPercent,
    total: (f) => (ratio(f?.cart_count, f?.open_count) == null ? null : (f.cart_count / f.open_count) * 100),
  },
  {
    key: 'orders',
    label: 'Заказы',
    tone: 'positive',
    format: fmtNumber,
    total: (f) => f?.order_count ?? null,
    organic: (f, a) => (f == null ? null : f.order_count - (a?.orders ?? 0)),
  },
  {
    key: 'order_conversion',
    label: 'Конверсия в заказ, %',
    tone: 'positive',
    format: fmtPercent,
    total: (f) => (ratio(f?.order_count, f?.cart_count) == null ? null : (f.order_count / f.cart_count) * 100),
  },
  { key: 'order_sum', label: 'Заказы, ₽', format: fmtCurrency, total: (f) => f?.order_sum ?? null },
  { key: 'buyout_sum', label: 'Выкупы, ₽', format: fmtCurrency, total: (f) => f?.buyout_sum ?? null },
  {
    key: 'cost_per_order',
    label: 'Стоимость заказа, ₽',
    format: fmtCurrency,
    total: (f, a) => ratio(a?.spend, f?.order_count),
  },
  {
    key: 'cost_per_cart',
    label: 'Стоимость корзины, ₽',
    format: fmtCurrency,
    total: (f, a) => ratio(a?.spend, f?.cart_count),
  },
  {
    key: 'drr_orders',
    label: 'ДРР от заказов, %',
    format: fmtPercent,
    total: (f, a) => (ratio(a?.spend, f?.order_sum) == null ? null : (a.spend / f.order_sum) * 100),
  },
  {
    key: 'drr_sales',
    label: 'ДРР от продаж, %',
    format: fmtPercent,
    total: (f, a) => (ratio(a?.spend, f?.buyout_sum) == null ? null : (a.spend / f.buyout_sum) * 100),
  },
  {
    key: 'buyout_percent',
    label: 'Процент выкупа, %',
    format: fmtPercent,
    total: (f) =>
      ratio(f?.buyout_count, f?.order_count) == null ? null : (f.buyout_count / f.order_count) * 100,
  },
]

/** Sum every campaign's daily rows into per-date ad totals. */
function aggregateAdsByDate(advertising = []) {
  const byDate = new Map()
  for (const campaign of advertising) {
    for (const day of campaign.daily ?? []) {
      const acc = byDate.get(day.stat_date) ?? {
        spend: 0,
        views: 0,
        clicks: 0,
        add_to_cart: 0,
        orders: 0,
      }
      acc.spend += day.spend
      acc.views += day.views
      acc.clicks += day.clicks
      acc.add_to_cart += day.add_to_cart
      acc.orders += day.orders
      byDate.set(day.stat_date, acc)
    }
  }
  return byDate
}

/**
 * Build the matrix for one `SkuDetailResponse`.
 *
 * Row values are flat, in day-major order: for day index `d` and traffic
 * column index `c` (within TRAFFIC_COLUMNS) the cell lives at
 * `values[d * TRAFFIC_COLUMNS.length + c]`.
 *
 * @returns {{days: Array<{iso: string, label: string}>,
 *   rows: Array<{key: string, label: string, values: string[]}>}}
 */
export function buildMetricsMatrix(product) {
  const window = product?.window
  if (!window) return { days: [], rows: [] }

  const isoDays = isoDateRange(window.start, window.end)
  const funnelByDate = new Map((product.funnel ?? []).map((row) => [row.stat_date, row]))
  const adsByDate = aggregateAdsByDate(product.advertising)

  const rows = METRIC_DEFS.map((def) => ({
    key: def.key,
    label: def.label,
    tone: def.tone ?? null,
    values: isoDays.flatMap((iso) => {
      const funnel = funnelByDate.get(iso)
      const ads = adsByDate.get(iso)
      return TRAFFIC_COLUMNS.map((column) => {
        const compute = def[column.key === 'total' ? 'total' : column.key === 'organic' ? 'organic' : 'none']
        return def.format(compute ? compute(funnel, ads) : null)
      })
    }),
  }))

  return { days: isoDays.map((iso) => ({ iso, label: dayLabel(iso) })), rows }
}
