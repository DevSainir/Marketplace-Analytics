/**
 * The chart both pages draw: one plot, and whichever metrics the reader picked.
 *
 * It replaced a carousel of ten saved questions. Each page is already a table
 * of every metric by day — what a chart adds is putting two or three of them
 * side by side, and WHICH ones is the reader's question, not ours. So there is
 * no slide list, no titles and no tabs: a set of metrics, and a plot.
 *
 * The pages differ only in which metrics they CAN offer — a per-SKU window has
 * prices and CTR, an account-wide sum does not — so the catalogue is a
 * parameter and everything else is shared.
 */
import {
  AXIS_GUTTER_PX,
  SERIES_COLORS,
  buildChartOption,
  gutterFor,
} from '@/modules/monitoring/chartOptions'
import { COLUMNS_PER_DAY, TRAFFIC_COLUMNS } from '@/modules/monitoring/metricsMatrix'

/** Column index of each backend bucket within a day section of `row.cells`. */
const BUCKET_INDEX = new Map(TRAFFIC_COLUMNS.map((column, index) => [column.key, index]))

/**
 * The metrics on offer, grouped for the eye only.
 *
 * «Реклама», «Воронка» and «Общие» are where a reader LOOKS for a metric, not
 * how the chart treats it. What the chart treats differently is the unit —
 * metrics sharing one share an axis — and the mark.
 *
 * `type: 'bar'` on остатки, корзины and заказы, and deliberately no `stack`:
 * they stand side by side as separate columns per day. Stacked they would draw
 * a total that means nothing — a cart is not a unit of stock.
 */
export const SKU_METRIC_GROUPS = [
  {
    title: 'Реклама',
    items: [
      { key: 'views', metric: 'views', bucket: 'total', name: 'Показы', unit: 'number' },
      { key: 'clicks', metric: 'clicks', bucket: 'total', name: 'Клики', unit: 'number' },
      { key: 'spend', metric: 'spend', bucket: 'total', name: 'Затраты, ₽', unit: 'currency' },
      { key: 'cpc', metric: 'cpc', bucket: 'total', name: 'CPC, ₽', unit: 'currency' },
      { key: 'ctr', metric: 'ctr', bucket: 'total', name: 'CTR, %', unit: 'percent' },
      {
        key: 'drr_orders',
        metric: 'drr_orders',
        bucket: 'total',
        name: 'ДРР от заказов, %',
        unit: 'percent',
      },
      {
        key: 'drr_sales',
        metric: 'drr_sales',
        bucket: 'total',
        name: 'ДРР от продаж, %',
        unit: 'percent',
      },
    ],
  },
  {
    title: 'Воронка',
    items: [
      {
        key: 'carts',
        metric: 'carts',
        bucket: 'total',
        name: 'Корзины, шт',
        unit: 'number',
        type: 'bar',
      },
      {
        key: 'orders',
        metric: 'orders',
        bucket: 'total',
        name: 'Заказы, шт',
        unit: 'number',
        type: 'bar',
      },
      {
        key: 'cart_conversion',
        metric: 'cart_conversion',
        bucket: 'total',
        name: 'Конверсия в корзину, %',
        unit: 'percent',
      },
      {
        key: 'order_conversion',
        metric: 'order_conversion',
        bucket: 'total',
        name: 'Конверсия в заказ, %',
        unit: 'percent',
      },
      {
        key: 'buyout_percent',
        metric: 'buyout_percent',
        bucket: 'total',
        name: 'Процент выкупа, %',
        unit: 'percent',
      },
    ],
  },
  {
    title: 'Общие',
    items: [
      {
        key: 'seller_price',
        metric: 'seller_price',
        source: 'priceRows',
        name: 'Цена продавца, ₽',
        unit: 'currency',
      },
      {
        key: 'customer_price',
        metric: 'customer_price',
        source: 'priceRows',
        name: 'Цена покупателя, ₽',
        unit: 'currency',
      },
      {
        // «На складах» only: the two in-transit legs answer a different
        // question (goods already moving) and would overstate what a buyer can
        // actually order today.
        key: 'stock_quantity',
        metric: 'stock_quantity',
        source: 'stockRows',
        name: 'Остатки на складах, шт',
        unit: 'number',
        type: 'bar',
      },
    ],
  },
]

/** Index a group list by metric key, for resolving a selection. */
function metricsByKey(groups) {
  return Object.fromEntries(groups.flatMap((group) => group.items.map((item) => [item.key, item])))
}

/** What the SKU chart opens on: two units, so neither flattens the other. */
export const SKU_DEFAULT_METRICS = ['spend', 'drr_sales']

/**
 * The account-wide catalogue — shorter, because not every metric survives
 * being summed over an account.
 *
 * Prices and СПП are per-card facts: the average price of a T-shirt and a mug
 * is a number about nothing. «Процент выкупа» is a lagged cohort ratio the
 * aggregate endpoint does not compute. CTR and CPC need the advertising
 * clicks and показы of one card's campaigns, which the summed matrix does not
 * carry. Each is absent rather than approximated.
 */
export const AGGREGATE_METRIC_GROUPS = [
  {
    title: 'Реклама',
    items: [
      { key: 'views', metric: 'views', bucket: 'total', name: 'Показы', unit: 'number' },
      { key: 'clicks', metric: 'clicks', bucket: 'total', name: 'Клики', unit: 'number' },
      { key: 'spend', metric: 'spend', bucket: 'total', name: 'Затраты, ₽', unit: 'currency' },
      {
        key: 'drr_orders',
        metric: 'drr_orders',
        bucket: 'total',
        name: 'ДРР от заказов, %',
        unit: 'percent',
      },
    ],
  },
  {
    title: 'Воронка',
    items: [
      {
        key: 'carts',
        metric: 'carts',
        bucket: 'total',
        name: 'Корзины, шт',
        unit: 'number',
        type: 'bar',
      },
      {
        key: 'orders',
        metric: 'orders',
        bucket: 'total',
        name: 'Заказы, шт',
        unit: 'number',
        type: 'bar',
      },
      {
        key: 'cart_conversion',
        metric: 'cart_conversion',
        bucket: 'total',
        name: 'Конверсия в корзину, %',
        unit: 'percent',
      },
      {
        key: 'order_conversion',
        metric: 'order_conversion',
        bucket: 'total',
        name: 'Конверсия в заказ, %',
        unit: 'percent',
      },
    ],
  },
  {
    title: 'Общие',
    items: [
      {
        key: 'order_sum',
        metric: 'order_sum',
        bucket: 'total',
        name: 'Заказы, ₽',
        unit: 'currency',
      },
      {
        key: 'orders_organic',
        metric: 'orders',
        bucket: 'organic',
        name: 'Заказы органика, шт',
        unit: 'number',
      },
      {
        key: 'stock_total',
        metric: 'stock_total',
        source: 'stockTotalRows',
        name: 'Остатки, шт',
        unit: 'number',
        type: 'bar',
      },
    ],
  },
]

/** What the account-wide chart opens on. */
export const AGGREGATE_DEFAULT_METRICS = ['order_sum', 'drr_orders']

/**
 * The two ways of putting unlike metrics on one plot.
 *
 * `absolute` keeps real values, one axis per unit. `index` rebases every series
 * to 100 at the window's first day, so what is compared is SHAPE — the
 * documented answer to metrics whose scales do not fit together. Offered, never
 * default: the baseline day is arbitrary, and the hover reads the real value
 * underneath either way.
 */
export const CHART_MODES = [
  { key: 'absolute', label: 'Значения' },
  { key: 'index', label: 'Индекс' },
]

/**
 * The per-day values of one metric, read straight out of the display matrix's
 * cells — a lookup, not a computation.
 */
function readSeries(view, series) {
  const rows = view[series.source ?? 'rows'] ?? []
  const row = rows.find((candidate) => candidate.key === series.metric)
  if (!row) return view.days.map(() => null)
  // A mini-block row («Цены», «Остатки») already carries one cell per day.
  if (series.source) return row.cells.map((cell) => cell.raw ?? null)

  const column = BUCKET_INDEX.get(series.bucket)
  if (column === undefined) return view.days.map(() => null)
  return view.days.map((_, day) => row.cells[day * COLUMNS_PER_DAY + column]?.raw ?? null)
}

/** Two decimals, the way the backend rounds every ratio it serves. */
const round2 = (value) => Math.round(value * 100) / 100

/**
 * Rebase a series to 100 at its first reported day, keeping the real values.
 *
 * `raw` is what the hover reads: an index is a shape, and a reader who wants to
 * know what «118» meant in roubles must not leave the chart to find out.
 */
function indexed(data, active) {
  if (!active) return { data }
  const base = data.find((value) => value != null && value !== 0)
  if (base == null) return { data }
  return {
    data: data.map((value) => (value == null ? null : round2((value / base) * 100))),
    raw: data,
  }
}

/**
 * Build the chart from the live display matrix.
 *
 * @param {object} view A display matrix (`matrixView` shape).
 * @param {{metrics?: string[], groups?: Array<object>, mode?: string}} [options]
 *   The reader's picks, and the catalogue to resolve them against.
 * @returns {object|null} `{dayCount, axisGutter, legend, empty, option}`, or
 *   null when the window has no days at all.
 */
export function buildMetricChart(view, { metrics = [], groups = [], mode = 'absolute' } = {}) {
  if (!view?.days?.length) return null
  const days = view.days.map((day) => day.iso)
  const indexMode = mode === 'index'
  const catalogue = metricsByKey(groups)

  const series = metrics
    .map((key) => catalogue[key])
    .filter(Boolean)
    .map((entry, index) => ({
      name: entry.name,
      type: entry.type ?? 'line',
      colorIndex: index,
      unit: entry.unit ?? 'number',
      ...indexed(readSeries(view, entry), indexMode),
    }))

  return {
    dayCount: days.length,
    // The frozen column holds ONE column of labels per axis drawn — and in
    // index mode exactly one axis is drawn, whatever the picked metrics
    // measure. Sizing it from the metrics' units regardless is what left a
    // gaping margin beside a single «инд.» scale, and made the margin jump
    // when a pick added a unit without adding an axis.
    axisGutter: indexMode || !series.length ? AXIS_GUTTER_PX : gutterFor(series),
    legend: series.map((entry, index) => ({
      name: entry.name,
      color: SERIES_COLORS[index % SERIES_COLORS.length],
    })),
    empty: !series.length || series.every((entry) => entry.data.every((value) => value == null)),
    option: buildChartOption({ days, indexMode, series }),
  }
}
