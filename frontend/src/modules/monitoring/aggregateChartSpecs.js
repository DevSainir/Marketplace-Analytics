/**
 * Which charts the account-wide «Графики» page draws, and why it is a shorter
 * list than the per-SKU page's.
 *
 * Not every metric survives being summed over an account:
 *
 * * Counts and money add up, so «Заказы, ₽», «Клики» and «Затраты» are honest
 *   sums.
 * * Ratios do NOT. «Конверсия» and «ДРР» are recomputed by the backend from the
 *   summed totals — the average of per-SKU conversions is not the account's
 *   conversion, and reads wildly high the moment a low-traffic card converts
 *   well.
 * * «Цены» and «СПП» are per-card facts with no account-level meaning: the
 *   average price of a T-shirt and a mug is a number about nothing. They are
 *   absent rather than approximated.
 * * «Процент выкупа» is a lagged cohort ratio the aggregate endpoint does not
 *   compute (see `SkuSummaryItem` for why it cannot be answered over an
 *   arbitrary window), and «Выкупы, ₽» is derived from it, so both go.
 * * The traffic-type split is absent for the reason in
 *   `AdvertisingRepository.daily_totals`: a bucket is a per-card judgement
 *   about a campaign-day, and does not survive summation.
 *
 * Everything else — the theme, the scrolling ribbon, the pinned axis — is the
 * per-SKU page's, reused through `buildSpecs`.
 */
import { buildSpecs } from '@/modules/monitoring/chartSpecs'

const M = {
  order_sum: { metric: 'order_sum', bucket: 'total', name: 'Заказы, ₽', unit: 'currency' },
  spend: { metric: 'spend', bucket: 'total', name: 'Затраты, ₽', unit: 'currency' },
  views: { metric: 'views', bucket: 'total', name: 'Показы', unit: 'number' },
  clicks: { metric: 'clicks', bucket: 'total', name: 'Клики', unit: 'number' },
  carts: { metric: 'carts', bucket: 'total', name: 'Корзины', unit: 'number' },
  orders: { metric: 'orders', bucket: 'total', name: 'Заказы, шт', unit: 'number' },
  orders_organic: {
    metric: 'orders',
    bucket: 'organic',
    name: 'Заказы органика, шт',
    unit: 'number',
    colorIndex: 5,
  },
  stock_total: {
    metric: 'stock_total',
    source: 'stockTotalRows',
    name: 'Остаток, шт',
    unit: 'number',
  },
  drr_orders: { metric: 'drr_orders', bucket: 'total', name: 'ДРР от заказов, %', unit: 'percent' },
  cart_conversion: {
    metric: 'cart_conversion',
    bucket: 'total',
    name: 'В корзину, %',
    unit: 'percent',
  },
  order_conversion: {
    metric: 'order_conversion',
    bucket: 'total',
    name: 'В заказ, %',
    unit: 'percent',
  },
}

const line = (key, extra = {}) => ({ ...M[key], type: 'line', ...extra })
const bar = (key, extra = {}) => ({ ...M[key], type: 'bar', ...extra })

/** «Общий» offers everything the aggregate endpoint actually serves. */
export const AGGREGATE_METRICS = Object.entries(M).map(([key, entry]) => ({
  key,
  name: entry.name,
  unit: entry.unit,
}))
export const AGGREGATE_DEFAULT_OVERVIEW = ['order_sum', 'spend', 'drr_orders']

const FUNNEL_SERIES = [line('clicks'), line('carts'), line('orders')]

const AGGREGATE_SPECS = [
  {
    key: 'overview',
    tab: 'Общий',
    title: 'Свой набор метрик по всем артикулам',
    pickable: true,
    series: [],
  },
  {
    key: 'sales',
    tab: 'Выручка',
    title: 'Сколько заказали в рублях и в штуках',
    // Two units, so both are legible at full height — and the gap between them
    // IS the average cheque moving, which neither says on its own.
    series: [bar('order_sum'), line('orders')],
  },
  {
    key: 'ads',
    tab: 'Реклама',
    title: 'Сколько потратили, сколько заказов принесло и какой ценой',
    // Volume as bars, efficiency as a line — the shape ad dashboards use.
    series: [bar('spend'), line('orders'), line('drr_orders')],
  },
  {
    key: 'funnel',
    tab: 'Воронка',
    title: 'Где теряются покупатели за период',
    funnel: true,
    series: [],
  },
  {
    key: 'conversion',
    tab: 'Конверсии',
    title: 'Как менялись конверсии между шагами',
    series: [line('cart_conversion'), line('order_conversion')],
  },
  {
    key: 'stages',
    tab: 'Этапы по дням',
    title: 'Клики, корзины и заказы по дням',
    panels: true,
    series: FUNNEL_SERIES,
  },
  {
    key: 'traffic',
    tab: 'Трафик',
    title: 'Сколько реклама показала и сколько из этого кликнули',
    series: [bar('views'), line('clicks')],
  },
  {
    key: 'orders_mix',
    tab: 'Реклама и органика',
    title: 'Сколько заказов принесла реклама, а сколько органика',
    // The gap between the lines IS the advertising half — the backend already
    // took the difference, this page adds nothing.
    series: [line('orders'), line('orders_organic')],
  },
  {
    key: 'stock',
    tab: 'Остатки и продажи',
    title: 'На сколько хватит остатка при таком темпе заказов',
    series: [line('stock_total', { area: true }), line('orders')],
  },
]

/**
 * Build the «Графики» slides from an aggregate display matrix.
 *
 * @param {object} view A display matrix built by `buildMetricsMatrix`.
 * @returns {Array<object>} Slides for `MetricsChartsPanel`.
 */
export function buildAggregateChartSpecs(view, options = {}) {
  return buildSpecs(view, AGGREGATE_SPECS, {
    overview: AGGREGATE_DEFAULT_OVERVIEW,
    ...options,
    catalogue: M,
  })
}
