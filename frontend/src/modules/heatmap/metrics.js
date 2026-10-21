/**
 * The heatmap's metric catalogue: what each backend key is called on screen,
 * how its value is printed, and which end of it is good.
 *
 * Keys are the backend's (`MetricKey` in `heatmap/schemas.py`), shared
 * verbatim; this file owns only presentation — the same split the monitoring
 * matrix uses. The direction is what the colour is built on, so it is the one
 * field here with consequences: «меньше — лучше» for every cost ratio (DRR,
 * CPC, CPM, CPO) and for the ad budget, «нейтрально» for prices and stock,
 * which have no better end, and «больше — лучше» for everything else.
 *
 * Money names carry no currency; every figure carries its own sign
 * («1 240с», «4 120₽») from `currencyOf` — the prices' for prices and order
 * sums, the campaigns' for spend and its costs, the settlement's for revenue
 * and profit. A workspace settled in KGS is priced in RUB, so one workspace-wide
 * unit was wrong for some figure whichever unit it was.
 */
import { currencySign, formatNumber } from '@/core/utils/format'

/** @typedef {'count'|'money'|'percent'} Unit */
/** @typedef {'up'|'down'|'neutral'} Direction */
/** @typedef {'prices'|'ads'|'settlement'} CurrencySource */

/**
 * @type {Array<{key: string, label: string, unit: Unit, direction: Direction,
 *   group: string, settled?: boolean, currencyOf?: CurrencySource}>}
 */
export const METRICS = [
  { key: 'orders', label: 'Заказы, шт', unit: 'count', direction: 'up', group: 'Воронка' },
  {
    key: 'order_sum',
    label: 'Заказы',
    unit: 'money',
    currencyOf: 'orders',
    direction: 'up',
    group: 'Воронка',
  },
  { key: 'opens', label: 'Переходы в карточку', unit: 'count', direction: 'up', group: 'Воронка' },
  { key: 'carts', label: 'Корзины', unit: 'count', direction: 'up', group: 'Воронка' },
  {
    key: 'cart_conversion',
    label: 'Конверсия в корзину, %',
    unit: 'percent',
    direction: 'up',
    group: 'Воронка',
  },
  {
    key: 'order_conversion',
    label: 'Конверсия в заказ, %',
    unit: 'percent',
    direction: 'up',
    group: 'Воронка',
  },
  {
    key: 'organic_opens',
    label: 'Переходы без рекламы',
    unit: 'count',
    direction: 'up',
    group: 'Воронка',
  },
  {
    key: 'spend',
    label: 'Расход на рекламу',
    unit: 'money',
    currencyOf: 'ads',
    direction: 'down',
    group: 'Реклама',
  },
  { key: 'ad_views', label: 'Показы рекламы', unit: 'count', direction: 'up', group: 'Реклама' },
  { key: 'ad_clicks', label: 'Клики по рекламе', unit: 'count', direction: 'up', group: 'Реклама' },
  { key: 'ctr', label: 'CTR, %', unit: 'percent', direction: 'up', group: 'Реклама' },
  {
    key: 'cpc',
    label: 'CPC',
    unit: 'money',
    currencyOf: 'ads',
    direction: 'down',
    group: 'Реклама',
  },
  {
    key: 'cpm',
    label: 'CPM',
    unit: 'money',
    currencyOf: 'ads',
    direction: 'down',
    group: 'Реклама',
  },
  { key: 'ad_orders', label: 'Заказы с рекламы', unit: 'count', direction: 'up', group: 'Реклама' },
  { key: 'ad_cr', label: 'CR рекламы, %', unit: 'percent', direction: 'up', group: 'Реклама' },
  {
    key: 'cpo',
    label: 'CPO',
    unit: 'money',
    currencyOf: 'ads',
    direction: 'down',
    group: 'Реклама',
  },
  {
    key: 'drr_orders',
    label: 'ДРР от заказов, %',
    unit: 'percent',
    direction: 'down',
    group: 'Реклама',
  },
  {
    key: 'seller_price',
    label: 'Цена до СПП',
    unit: 'money',
    currencyOf: 'prices',
    direction: 'neutral',
    group: 'Цены и остатки',
  },
  {
    key: 'customer_price',
    label: 'Цена с СПП',
    unit: 'money',
    currencyOf: 'prices',
    direction: 'neutral',
    group: 'Цены и остатки',
  },
  {
    key: 'spp',
    label: 'СПП, %',
    unit: 'percent',
    direction: 'neutral',
    group: 'Цены и остатки',
  },
  {
    key: 'stock',
    label: 'Остатки на складах, шт',
    unit: 'count',
    direction: 'neutral',
    group: 'Цены и остатки',
  },
  {
    key: 'revenue',
    label: 'Выручка',
    unit: 'money',
    currencyOf: 'settlement',
    direction: 'up',
    group: 'Финансы (отчёты WB)',
    settled: true,
  },
  {
    key: 'sales',
    label: 'Продажи, шт',
    unit: 'count',
    direction: 'up',
    group: 'Финансы (отчёты WB)',
    settled: true,
  },
  {
    key: 'profit',
    label: 'Чистая прибыль',
    unit: 'money',
    currencyOf: 'settlement',
    direction: 'up',
    group: 'Финансы (отчёты WB)',
    settled: true,
  },
  {
    key: 'margin',
    label: 'Маржинальность, %',
    unit: 'percent',
    direction: 'up',
    group: 'Финансы (отчёты WB)',
    settled: true,
  },
]

const BY_KEY = new Map(METRICS.map((metric) => [metric.key, metric]))

/**
 * Metrics whose week or month is the SUM of its days — counts and money flows.
 * A hand-set norm is per day, so for these it is compared with a column's daily
 * average; ratios, prices and the stock level are compared as they are.
 */
const ADDS_UP = new Set([
  'orders',
  'order_sum',
  'opens',
  'carts',
  'organic_opens',
  'spend',
  'ad_views',
  'ad_clicks',
  'ad_orders',
  'revenue',
  'sales',
  'profit',
])

/**
 * @param {(typeof METRICS)[number]} metric
 * @returns {boolean} Whether a column of it is the sum of its days.
 */
export function addsUp(metric) {
  return ADDS_UP.has(metric.key)
}

/** The picker's option groups, in catalogue order. */
export const METRIC_GROUPS = [...new Set(METRICS.map((metric) => metric.group))].map((group) => ({
  label: group,
  metrics: METRICS.filter((metric) => metric.group === group),
}))

/**
 * @param {string|null} key
 * @returns {(typeof METRICS)[number]|null}
 */
export function metricOf(key) {
  return (key && BY_KEY.get(key)) || null
}

/**
 * The currency a money metric is in, from the grid's three.
 *
 * @param {(typeof METRICS)[number]} metric
 * @param {{prices?: string, ads?: string[], orders?: string, settlement?: string}} currencies
 * @returns {string|string[]} An ISO code, the codes of a window across the ad
 *   account's 2026-08-20 switch, or `''`.
 */
export function currencyOf(metric, currencies) {
  if (!metric || metric.unit !== 'money') return ''
  if (metric.currencyOf === 'ads') return currencies?.ads ?? []
  return currencies?.[metric.currencyOf] ?? ''
}

/**
 * A metric's name as the picker shows it. No currency: the sign is on every
 * figure instead (`formatValue`).
 *
 * @param {(typeof METRICS)[number]} metric
 * @returns {string}
 */
export function metricLabel(metric) {
  return metric.label
}

/**
 * Print one cell's value in its metric's unit. `—` for a cell with nothing to show.
 *
 * Money is whole units: a heatmap is read for its pattern, and kopecks on
 * every one of a few thousand cells are noise. Percentages keep one decimal —
 * a CTR of 1.4 against 1.9 is the whole story.
 *
 * @param {number|null} value
 * @param {Unit} unit
 * @param {string|string[]} [currency] For money, what `currencyOf` says it is in.
 * @returns {string}
 */
export function formatValue(value, unit, currency = '') {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  if (unit === 'percent') {
    return value.toLocaleString('ru-RU', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
  }
  const figure = formatNumber(Math.round(value))
  return unit === 'money' ? figure + currencySign(currency) : figure
}

/**
 * One cell of a row as printed: its value, signed with the cell's own currency
 * where the row names one per cell (spend, CPC, CPM, CPO — `units`), with the
 * grid's otherwise.
 *
 * Across 20.08.2026 the spend is roubles in one column and som in the next, so
 * a grid-wide sign would be wrong on half of them; a cell over both has no
 * figure (the backend sends null).
 *
 * @param {object} row A `HeatmapRow`.
 * @param {number|'total'} at A column index, or the row's «Итого».
 * @param {(typeof METRICS)[number]|null} metric
 * @param {object} currencies The grid's currencies (see {@link currencyOf}).
 * @param {boolean} [second] Read the second metric's values.
 * @returns {string}
 */
export function cellText(row, at, metric, currencies, second = false) {
  const values = second ? row.values2 : row.values
  const value = at === 'total' ? (second ? row.total2 : row.total) : values?.[at]
  const units = second ? row.units2 : row.units
  const own = at === 'total' ? (second ? row.total_unit2 : row.total_unit) : units?.[at]
  const currency = units ? own : currencyOf(metric, currencies)
  return formatValue(value, metric?.unit ?? 'count', currency)
}
