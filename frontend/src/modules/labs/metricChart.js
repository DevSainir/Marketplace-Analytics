/**
 * The chart both pages draw: one plot, and whichever metrics the reader picked.
 *
 * It replaced a carousel of ten saved questions. Each page is already a table
 * of every metric by day — what a chart adds is putting several of them side by
 * side, and WHICH ones is the reader's question, not ours. So there is no slide
 * list and no tabs: a set of metrics, and a plot.
 *
 * The pages differ only in which metrics they CAN offer — a per-SKU window has
 * prices and CTR, an account-wide sum does not — so the catalogue is a
 * parameter and everything else is shared.
 *
 * Metrics are plotted as an INDEX — rebased to 100 at the window's first
 * reported day. There is no «Значения» mode any more, because there never was
 * an honest one: «Заказы, ₽» at 500 000 beside «Затраты, ₽» at 7 000 share a
 * unit, therefore an axis, and the smaller of the two is a flat line at the
 * bottom of the plot. What a reader compares here is SHAPE; the real values are
 * a hover away, and the table above holds every one of them.
 *
 * ЗАКАЗЫ are the exception, and the reason the plot is readable at all. The
 * left-hand scale is a scale of заказов, so a series that counts заказы is
 * drawn AS IT IS: 120 заказов lands a little above the 120 line. That gives
 * every other series a real quantity to be a shape against, instead of a ruler
 * with no relationship to anything on the canvas.
 */
import {
  AXIS_GUTTER_PX,
  buildChartOption,
  colorForMetric,
  dayWidthFor,
  niceCeiling,
} from '@/modules/labs/chartOptions'
import { COLUMNS_PER_DAY, TRAFFIC_COLUMNS } from '@/modules/labs/metricsMatrix'

/** Column index of each backend bucket within a day section of `row.cells`. */
const BUCKET_INDEX = new Map(TRAFFIC_COLUMNS.map((column, index) => [column.key, index]))

/**
 * The backend metric the left-hand ruler is a scale of.
 *
 * Matched on `metric` rather than on the catalogue key, so every entry reading
 * that row is covered by one rule: «Заказы, шт» on both pages, and «Заказы
 * органика, шт», which is the same count of the same thing through one traffic
 * bucket. All three are true on a scale of заказов and are drawn unrebased.
 *
 * «Заказы, ₽» is NOT one of them — it reads `order_sum`, and roubles on a scale
 * of заказов would be a number in the wrong units sitting on a real gridline.
 */
const RULER_METRIC = 'orders'

/**
 * The metrics on offer, in the order everything downstream reads them.
 *
 * The order is not cosmetic. It is the order of the chips, of the legend, of
 * the tooltip rows and — because the columns of a day are drawn in series order
 * — of the bars themselves, which is why «Корзины», «Заказы», «Остатки» stand
 * in that sequence on every day of every window. A selection is sorted back
 * into this order before it is drawn, so ticking the same three metrics in a
 * different sequence cannot produce a different chart.
 *
 * «Реклама», «Воронка» and «Общие» are where a reader LOOKS for a metric. The
 * chart uses them too, but only to group the hover.
 *
 * `type: 'bar'` on остатки, корзины and заказы, and deliberately no `stack`:
 * they stand side by side as separate columns per day. Stacked they would draw
 * a total that means nothing — a cart is not a unit of stock.
 */
export const SKU_METRIC_GROUPS = [
  {
    title: 'Реклама',
    items: [
      { key: 'spend', metric: 'spend', bucket: 'total', name: 'Затраты, ₽', unit: 'currency' },
      { key: 'views', metric: 'views', bucket: 'total', name: 'Показы', unit: 'number' },
      { key: 'clicks', metric: 'clicks', bucket: 'total', name: 'Клики', unit: 'number' },
      { key: 'ctr', metric: 'ctr', bucket: 'total', name: 'CTR, %', unit: 'percent' },
      { key: 'cpm', metric: 'cpm', bucket: 'total', name: 'CPM, ₽', unit: 'currency' },
      { key: 'cpc', metric: 'cpc', bucket: 'total', name: 'CPC, ₽', unit: 'currency' },
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
        key: 'cart_conversion',
        metric: 'cart_conversion',
        bucket: 'total',
        name: 'Конверсия в корзину, %',
        unit: 'percent',
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

/**
 * What the chart opens on — one advertising pair, one funnel pair, and the
 * rate that joins them.
 *
 * A blank plot makes the reader do work before the page says anything, and a
 * plot of everything says nothing. Затраты against показы is where the money
 * goes, корзины against заказы is what came back, and CTR is the hinge between
 * them; each of the five is a different colour and only two are columns.
 */
export const SKU_DEFAULT_METRICS = ['spend', 'views', 'ctr', 'carts', 'orders']

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
      { key: 'spend', metric: 'spend', bucket: 'total', name: 'Затраты, ₽', unit: 'currency' },
      { key: 'views', metric: 'views', bucket: 'total', name: 'Показы', unit: 'number' },
      { key: 'clicks', metric: 'clicks', bucket: 'total', name: 'Клики', unit: 'number' },
      // Where CTR sits on the per-SKU page. CTR itself cannot follow: «Клики»
      // here is the funnel's card opens, not advertising clicks.
      { key: 'cpm', metric: 'cpm', bucket: 'total', name: 'CPM, ₽', unit: 'currency' },
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
        key: 'cart_conversion',
        metric: 'cart_conversion',
        bucket: 'total',
        name: 'Конверсия в корзину, %',
        unit: 'percent',
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

/** The same opening question as the per-SKU page, minus the CTR it has no data for. */
export const AGGREGATE_DEFAULT_METRICS = ['spend', 'views', 'carts', 'orders']

/** Index a group list by metric key, each entry carrying its group's title. */
export function metricsByKey(groups) {
  return Object.fromEntries(
    groups.flatMap((group) =>
      group.items.map((item) => [item.key, { ...item, group: group.title }]),
    ),
  )
}

/** Catalogue position of each key — the one order everything downstream uses. */
function catalogueOrder(groups) {
  return new Map(groups.flatMap((group) => group.items).map((item, index) => [item.key, index]))
}

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
 * know what «118» meant in roubles must not leave the chart to find out. A
 * series plotted unrebased never gets one — there is no second number to show,
 * and «374 (374)» reads as a mistake.
 *
 * Exported for `chartScaling.js`, which re-indexes the same metric over WEEKS
 * rather than days: a weekly column is the sum of its days' real values, and
 * an index has to be rebased on the series it is actually drawn from.
 */
export function indexed(data) {
  const base = data.find((value) => value != null && value !== 0)
  if (base == null) return { data }
  return {
    data: data.map((value) => (value == null ? null : round2((value / base) * 100))),
    raw: data,
  }
}

/** The largest finite number in a list, or `null` when there is none. */
function maxOf(values) {
  const finite = values.filter((value) => value != null && Number.isFinite(value))
  return finite.length ? Math.max(...finite) : null
}

/**
 * Where the left-hand ruler tops out.
 *
 * The scale is a scale of ЗАКАЗОВ — the one quantity the page is about, and
 * the one series drawn against it unrebased. It is read off the window's orders
 * whether or not «Заказы» is ticked, so ticking a metric never moves the scale
 * under the others.
 *
 * The one thing that does raise it is a series that would otherwise be CUT: a
 * metric that tripled plots at 300 and a ruler stopping at 150 would draw it as
 * a line that stops, which is a lie a chart must not tell.
 *
 * Exported for `chartScaling.js`, whose weekly layout plots the same заказы
 * folded into weeks and must therefore read the same ruler.
 */
export function axisCeiling(view, catalogue, series) {
  const orders = catalogue.orders ? maxOf(readSeries(view, catalogue.orders)) : null
  const plotted = maxOf(series.flatMap((entry) => entry.data))
  // `niceCeiling` of nothing is the default ruler — a window with no заказы at
  // all still needs a scale, and 0-500 is the shape of the ones that do.
  return Math.max(niceCeiling(orders), plotted == null ? 0 : niceCeiling(plotted))
}

/**
 * The metrics a reader picked, resolved against the catalogue and read off the
 * matrix — everything a plot needs EXCEPT the decision how to draw them.
 *
 * Split out of :func:`buildMetricChart` so a second layout can read the same
 * series without a second copy of the catalogue lookup, the ordering rule and
 * the cell read. `chartScaling.js` (the sandbox's fit-to-the-card experiments)
 * is that second reader: it folds the counts into weeks before indexing them,
 * which it can only do from the REAL values.
 *
 * @param {object} view A display matrix (`matrixView` shape).
 * @param {{metrics?: string[], groups?: Array<object>}} [options]
 * @returns {Array<{key: string, name: string, type: string, unit: string,
 *   group: string, color: string, values: Array<number|null>,
 *   isRuler: boolean}>} In catalogue order, whatever order they were ticked in.
 */
export function metricSeriesSpecs(view, { metrics = [], groups = [] } = {}) {
  const catalogue = metricsByKey(groups)
  const order = catalogueOrder(groups)

  return metrics
    .filter((key) => catalogue[key])
    .sort((a, b) => order.get(a) - order.get(b))
    .map((key) => {
      const entry = catalogue[key]
      return {
        key,
        name: entry.name,
        type: entry.type ?? 'line',
        unit: entry.unit ?? 'number',
        group: entry.group,
        color: colorForMetric(key),
        values: readSeries(view, entry),
        // A scale of заказов: the one series drawn against it unrebased.
        isRuler: entry.metric === RULER_METRIC,
      }
    })
}

/**
 * Build the chart from the live display matrix.
 *
 * @param {object} view A display matrix (`matrixView` shape).
 * @param {{metrics?: string[], groups?: Array<object>, hover?: object}} [options]
 *   The reader's picks, the catalogue to resolve them against, and the live
 *   holder saying which series the cursor is on (see `focusedPoints`).
 * @returns {object|null} `{dayCount, axisGutter, legend, empty, option}`, or
 *   null when the window has no days at all.
 */
export function buildMetricChart(view, { metrics = [], groups = [], hover } = {}) {
  if (!view?.days?.length) return null
  const days = view.days.map((day) => day.iso)
  const catalogue = metricsByKey(groups)

  const series = metricSeriesSpecs(view, { metrics, groups }).map((spec) => ({
    name: spec.name,
    type: spec.type,
    unit: spec.unit,
    group: spec.group,
    color: spec.color,
    // Заказы are what the scale measures, so they are drawn as they are.
    ...(spec.isRuler ? { data: spec.values } : indexed(spec.values)),
  }))

  return {
    dayCount: days.length,
    // Pixels per day, so the ribbon and the plot are laid out to one number.
    dayWidth: dayWidthFor(days.length),
    // What the ribbon re-pins on: a new window or a new pick is a new question,
    // and a question is asked of the LAST few days. Derived from the series
    // rather than counted, so an unrelated re-render does not look like one.
    key: `${days.length}:${series.map((entry) => entry.name).join('|')}`,
    // One axis, always — so one column, always.
    axisGutter: AXIS_GUTTER_PX,
    legend: series.map((entry) => ({ name: entry.name, color: entry.color })),
    empty: !series.length || series.every((entry) => entry.data.every((value) => value == null)),
    option: buildChartOption({
      days,
      axisMax: axisCeiling(view, catalogue, series),
      hover,
      series,
    }),
  }
}
