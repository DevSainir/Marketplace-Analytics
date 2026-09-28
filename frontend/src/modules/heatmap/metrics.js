/**
 * The heatmap's metric catalogue: what each backend key is called on screen,
 * how its value is printed, and which end of it is good.
 *
 * Keys are the backend's (`MetricKey` in `heatmap/schemas.py`), shared
 * verbatim; this file owns only presentation — the same split the monitoring
 * matrix uses. The direction is what the colour is built on, so it is the one
 * field here with consequences: «меньше — лучше» for every cost ratio (ДРР,
 * CPC, CPM, CPO) and for the ad budget, «нейтрально» for prices and stock,
 * which have no better end, and «больше — лучше» for everything else.
 *
 * Money labels carry no currency of their own: `metricLabel` appends the
 * кабинет's, because a кабинет settled in KGS is priced, advertised and paid
 * in KGS throughout, and a «₽» beside those figures was simply wrong.
 */
import { formatNumber } from '@/core/utils/format'

/** @typedef {'count'|'money'|'percent'} Unit */
/** @typedef {'up'|'down'|'neutral'} Direction */

/**
 * @type {Array<{key: string, label: string, unit: Unit, direction: Direction,
 *   group: string, settled?: boolean}>}
 */
export const METRICS = [
  { key: 'orders', label: 'Заказы, шт', unit: 'count', direction: 'up', group: 'Воронка' },
  { key: 'order_sum', label: 'Заказы', unit: 'money', direction: 'up', group: 'Воронка' },
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
    direction: 'down',
    group: 'Реклама',
  },
  { key: 'ad_views', label: 'Показы рекламы', unit: 'count', direction: 'up', group: 'Реклама' },
  { key: 'ad_clicks', label: 'Клики по рекламе', unit: 'count', direction: 'up', group: 'Реклама' },
  { key: 'ctr', label: 'CTR, %', unit: 'percent', direction: 'up', group: 'Реклама' },
  { key: 'cpc', label: 'CPC', unit: 'money', direction: 'down', group: 'Реклама' },
  { key: 'cpm', label: 'CPM', unit: 'money', direction: 'down', group: 'Реклама' },
  { key: 'ad_orders', label: 'Заказы с рекламы', unit: 'count', direction: 'up', group: 'Реклама' },
  { key: 'ad_cr', label: 'CR рекламы, %', unit: 'percent', direction: 'up', group: 'Реклама' },
  { key: 'cpo', label: 'CPO', unit: 'money', direction: 'down', group: 'Реклама' },
  {
    key: 'drr_orders',
    label: 'ДРР по заказам, %',
    unit: 'percent',
    direction: 'down',
    group: 'Реклама',
  },
  {
    key: 'seller_price',
    label: 'Цена до СПП',
    unit: 'money',
    direction: 'neutral',
    group: 'Цены и остатки',
  },
  {
    key: 'customer_price',
    label: 'Цена с СПП',
    unit: 'money',
    direction: 'neutral',
    group: 'Цены и остатки',
  },
  { key: 'spp', label: 'СПП, %', unit: 'percent', direction: 'neutral', group: 'Цены и остатки' },
  {
    key: 'stock',
    label: 'Остатки на складах WB, шт',
    unit: 'count',
    direction: 'neutral',
    group: 'Цены и остатки',
  },
  {
    key: 'revenue',
    label: 'Выручка',
    unit: 'money',
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
    label: 'Прибыль',
    unit: 'money',
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
 * A metric's name as the picker shows it: money gets the кабинет's currency.
 *
 * @param {(typeof METRICS)[number]} metric
 * @param {string} currency ISO code from the grid (`KGS`), empty until it loads.
 * @returns {string}
 */
export function metricLabel(metric, currency) {
  return metric.unit === 'money' && currency ? `${metric.label}, ${currency}` : metric.label
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
 * @returns {string}
 */
export function formatValue(value, unit) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  if (unit === 'percent') {
    return value.toLocaleString('ru-RU', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
  }
  return formatNumber(Math.round(value))
}
