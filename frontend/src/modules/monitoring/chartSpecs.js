/**
 * Which metric goes on which chart — the monitoring «Графики» block.
 *
 * The charts read the SAME numbers the table above them renders: the source is
 * `store.matrixView`, the live display matrix, so an edit or an undo moves the
 * chart with the table instead of leaving the two disagreeing. Every value is
 * already computed server-side (strict rule: no calculations in the frontend);
 * this module only picks cells out of the matrix and names the series. Where a
 * chart shows a composition, the stacking is ECharts' — nothing is summed here.
 *
 * One unit per chart, always: a chart with two y-scales makes any crossing of
 * its lines look like a relationship, so a second unit gets its own slide.
 */
import { COLUMNS_PER_DAY, TRAFFIC_COLUMNS } from '@/modules/monitoring/metricsMatrix'
import {
  AXIS_GUTTER_PX,
  SERIES_COLORS,
  buildChartOption,
  buildFunnelOption,
  gutterFor,
} from '@/modules/monitoring/chartOptions'

/**
 * Plot height. A single plot gets the standard one; a small-multiples chart
 * gets enough that each of its three panels is still a plot rather than a
 * horizon line.
 */
const CHART_HEIGHT = '340px'
// Height is the ONLY lever left for telling 97 from 118 apart. The axis cannot
// zoom to that band while a 215-spike day shares the panel, and the panel keeps
// the spike because dropping it would be a lie — so the band gets pixels
// instead. At 720 each of the three panels is ~190px of plot and a 20-unit move
// is ~18px; at the 440 it started from it was 6, which is what «not
// distinguishable» meant. Vertical space is the cheap thing on this page.
const PANEL_CHART_HEIGHT = '720px'
/** A funnel needs height for its stages, not for a day axis. */
const FUNNEL_CHART_HEIGHT = '420px'

/** Column index of each backend bucket within a day section of `row.cells`. */
const BUCKET_INDEX = new Map(TRAFFIC_COLUMNS.map((column, index) => [column.key, index]))

/**
 * The advertising buckets, in the table's own column order and labelled the
 * way its «Тип получения трафика» header does. `uni_catalog` is absent on
 * purpose: it is a legacy WB zone kept for workbook parity and always empty,
 * so it would only ever add a dead legend entry.
 *
 * `colorIndex` pins each bucket to one palette slot, so «CPC · поиск» is the
 * same violet on every slide it appears on. Slot 6 (green) is skipped here and
 * reserved for «Органика» below — seven ad buckets plus organic is exactly the
 * eight-slot palette, and a ninth bucket cannot simply be appended.
 */
const AD_BUCKETS = [
  { bucket: 'uni_search', name: 'Единая · поиск', colorIndex: 0 },
  { bucket: 'uni_shelves', name: 'Единая · полки', colorIndex: 1 },
  { bucket: 'manual_search', name: 'Руч. поиск · поиск', colorIndex: 2 },
  { bucket: 'manual_catalog', name: 'Руч. поиск · каталог', colorIndex: 3 },
  { bucket: 'manual_shelves', name: 'Руч. полки · полки', colorIndex: 4 },
  { bucket: 'cpc_search', name: 'CPC · поиск', colorIndex: 6 },
  { bucket: 'cpc_shelves', name: 'CPC · полки', colorIndex: 7 },
]

/**
 * «Органика» — everything the day did WITHOUT advertising. It goes first, so
 * it forms the stable base of the stack and the ad layers ride on top of it,
 * which is both the manager's mental model and far easier to read than an
 * organic band whose lower edge moves with the ad spend. Green rather than the
 * eighth slot's red: red on the biggest, healthiest band of the chart reads as
 * an alarm.
 */
const ORGANIC = { bucket: 'organic', name: 'Органика', colorIndex: 5 }

/**
 * The slides, in reading order: what the day earned, what it cost, how the
 * funnel moved, then the two compositions, then price and stock.
 *
 * `source` names the matrix block a series is read from — the default `rows`
 * is the day × bucket grid, while `priceRows`/`stockRows` are the mini blocks
 * whose rows carry ONE «Общая» cell per day (`bucket` is meaningless there).
 *
 * «Общая» is the funnel-wide column: CTR and CPM are deliberately absent from
 * it (a mixed column has no meaningful click-through rate), which is why the
 * conversion slide reads корзина/заказ/выкуп rather than CTR.
 */
/**
 * The metrics «Общий» offers, and the shape every other chart is built from.
 *
 * `unit` is per METRIC, not per chart, because a chart earns its keep by
 * pairing metrics that answer one question — and those rarely share a unit.
 * The builder gives each unit its own axis (see `chartUnits`).
 */
const METRICS = {
  order_sum: { metric: 'order_sum', bucket: 'total', name: 'Заказы, ₽', unit: 'currency' },
  buyout_sum: { metric: 'buyout_sum', bucket: 'total', name: 'Выкупы, ₽', unit: 'currency' },
  spend: { metric: 'spend', bucket: 'total', name: 'Затраты, ₽', unit: 'currency' },
  cpc: { metric: 'cpc', bucket: 'total', name: 'CPC, ₽', unit: 'currency' },
  cost_per_order: {
    metric: 'cost_per_order',
    bucket: 'total',
    name: 'Стоимость заказа, ₽',
    unit: 'currency',
  },
  customer_price: {
    metric: 'customer_price',
    source: 'priceRows',
    name: 'Цена покупателя, ₽',
    unit: 'currency',
  },
  views: { metric: 'views', bucket: 'total', name: 'Показы', unit: 'number' },
  clicks: { metric: 'clicks', bucket: 'total', name: 'Клики', unit: 'number' },
  carts: { metric: 'carts', bucket: 'total', name: 'Корзины', unit: 'number' },
  orders: { metric: 'orders', bucket: 'total', name: 'Заказы, шт', unit: 'number' },
  orders_organic: {
    metric: 'orders',
    bucket: 'organic',
    name: 'Заказы органика, шт',
    unit: 'number',
  },
  stock_total: {
    metric: 'stock_total',
    source: 'stockTotalRows',
    name: 'Остаток, шт',
    unit: 'number',
  },
  drr_sales: { metric: 'drr_sales', bucket: 'total', name: 'ДРР от продаж, %', unit: 'percent' },
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
  buyout_percent: {
    metric: 'buyout_percent',
    bucket: 'total',
    name: 'Процент выкупа, %',
    unit: 'percent',
  },
  spp: { metric: 'spp', source: 'priceRows', name: 'СПП, %', unit: 'percent' },
}

/**
 * What «Общий» starts on: revenue against the share advertising ate — the
 * money question, and two DIFFERENT units, so neither crushes the other.
 */
export const DEFAULT_OVERVIEW = ['order_sum', 'drr_sales']

/**
 * How many metrics «Общий» will draw at once.
 *
 * Not a arbitrary tidiness rule: dashboard guidance puts the readable ceiling
 * at four to six series, after which the advice is to facet or filter rather
 * than keep stacking. Google's own metric-comparison view goes further and
 * compares exactly two. Four is the generous end of that, and the picker stops
 * there rather than letting a reader build a chart nobody can read.
 */
export const MAX_OVERVIEW_METRICS = 4

/**
 * The two ways «Общий» can put unlike metrics on one plot.
 *
 * `absolute` keeps real values, one axis per unit — true numbers, but «Заказы,
 * ₽» at 500 000 flattens «Затраты, ₽» at 7 000 against the baseline, because
 * they are both roubles and therefore share a ruler.
 *
 * `index` is the documented answer to exactly that: rebase every series to 100
 * at the window's first day, so what is compared is SHAPE — did this rise while
 * that fell — on one axis, whatever the units. Its known weakness is that the
 * baseline day is arbitrary and a different one draws a different chart, which
 * is why it is a mode the reader chooses and never the default, and why the
 * hover still shows the real value underneath.
 */
export const OVERVIEW_MODES = [
  { key: 'absolute', label: 'Значения' },
  { key: 'index', label: 'Индекс (100 = первый день)' },
]

/** Every metric «Общий» can overlay, in picker order. */
export const OVERVIEW_METRICS = Object.entries(METRICS).map(([key, entry]) => ({
  key,
  name: entry.name,
  unit: entry.unit,
}))

/** A metric as a line, or as bars when it is the chart's subject rather than its context. */
const line = (key, extra = {}) => ({ ...METRICS[key], type: 'line', ...extra })
const bar = (key, extra = {}) => ({ ...METRICS[key], type: 'bar', ...extra })

/** The funnel's three stages, shared by both «Воронка» tabs. */
/** Shared by both «Воронка» tabs — the same numbers, drawn two ways. */
const FUNNEL_SERIES = [line('clicks'), line('carts'), line('orders')]

/**
 * The charts, each answering ONE question.
 *
 * The rule they are built to — taken from how advertising dashboards are
 * actually laid out — is that if you cannot say in a sentence why two metrics
 * share a chart, they should not. A lone series is a number on a wall: «Цена»
 * by itself says nothing you could act on, while price against demand asks
 * whether the last cut worked. So the standalone «Цены», «Конверсии» and
 * «Остатки» slides are gone, folded into the questions they belong to.
 */
const CHART_SPECS = [
  {
    key: 'overview',
    tab: 'Общий',
    title: 'Свой набор метрик',
    // The one chart with no fixed question: pick the metrics whose relationship
    // you are chasing today. Everything else here is a saved answer.
    pickable: true,
    series: [],
  },
  {
    key: 'sales',
    tab: 'Продажи',
    title: 'Что заказали, что выкупили и какая доля дошла',
    series: [bar('order_sum'), bar('buyout_sum'), line('buyout_percent')],
  },
  {
    key: 'ads',
    tab: 'Реклама',
    title: 'Сколько потратили, сколько заказов принесло и какой ценой',
    // The shape ad dashboards actually use: VOLUME as bars on one axis and
    // EFFICIENCY as a line on another, so you read «spent more» and «got more»
    // and «at what share» in one glance.
    //
    // Spend alone against ДРР said nothing, which is fair: a ratio with
    // neither of its halves on screen is a number with no story. «Заказы, шт»
    // is the half that fits — «Заказы, ₽» is fifty times the spend and would
    // flatten the bars it is meant to explain. And ONE ДРР line, not two: от
    // заказов and от продаж track each other so closely that the second was
    // just ink.
    series: [bar('spend'), line('orders'), line('drr_sales')],
  },
  {
    key: 'traffic',
    tab: 'Трафик',
    title: 'Сколько показов, сколько кликов и почём клик',
    series: [bar('views'), line('clicks'), line('cpc')],
  },
  {
    key: 'funnel',
    tab: 'Воронка',
    title: 'Где теряются покупатели за период',
    // A FUNNEL, not five day-series pretending to be one. The stages are the
    // window's totals drawn against each other, so the drop-off is the shape
    // itself and each stage carries its share of the one above — which the
    // funnel literature calls the actionable number.
    funnel: true,
    series: [],
  },
  {
    key: 'conversion',
    tab: 'Конверсии',
    title: 'Как менялись конверсии между шагами',
    // The trend half. A funnel is a snapshot and cannot show one, so the same
    // conversions are drawn over the days beside it — one axis, all percent.
    series: [line('cart_conversion'), line('order_conversion'), line('buyout_percent')],
  },
  {
    key: 'stages',
    tab: 'Этапы по дням',
    title: 'Клики, корзины и заказы по дням',
    // The counts, when what you want is the day one of them moved. Kept as
    // panels because клики run in the thousands and заказы in the tens.
    panels: true,
    series: FUNNEL_SERIES,
  },
  {
    key: 'spend_mix',
    tab: 'Расходы по типам',
    title: 'Из чего сложились затраты на рекламу',
    stack: 'spend',
    series: AD_BUCKETS.map((entry) => ({
      ...entry,
      metric: 'spend',
      unit: 'currency',
      type: 'bar',
    })),
  },
  {
    key: 'orders_mix',
    tab: 'Реклама и органика',
    title: 'Сколько заказов принесла реклама, а сколько органика',
    stack: 'orders',
    series: [
      { ...ORGANIC, metric: 'orders', unit: 'number', type: 'bar' },
      ...AD_BUCKETS.map((entry) => ({
        ...entry,
        metric: 'orders',
        unit: 'number',
        type: 'bar',
      })),
    ],
  },
  {
    key: 'price',
    tab: 'Цена и спрос',
    title: 'Двигался ли спрос, когда двигалась цена',
    // The pairing price analytics is built on: a price change is only
    // interesting next to what it did to the orders. СПП is deliberately NOT
    // here — it is a third thing, and a third unit means a third axis for a
    // question that only asked about two.
    series: [line('customer_price'), line('orders')],
  },
  {
    key: 'stock',
    tab: 'Остатки и продажи',
    title: 'На сколько хватит остатка при таком темпе заказов',
    // Both in штуках, so they share one axis and the comparison is direct —
    // which is what turns «остаток 400» into «дней на десять».
    series: [line('stock_total', { area: true }), line('orders')],
  },
]

/**
 * Rebase a series to 100 at its first reported day, keeping the real values.
 *
 * The `raw` half is what the hover reads: an index is a shape, and a reader
 * who wants to know what «118» meant in roubles must not have to leave the
 * chart to find out. A series with no first value cannot be rebased and is
 * returned untouched — it is all gaps anyway.
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

/** Two decimals, the way the backend rounds every ratio it serves. */
const round2 = (value) => Math.round(value * 100) / 100

/**
 * The per-day values of one metric row, read straight out of the display
 * matrix's cells — a lookup, not a computation.
 *
 * Mini-block rows (`priceRows`/`stockRows`) already carry one cell per day;
 * the main grid is day-major with a `COLUMNS_PER_DAY` stride, so the bucket's
 * column index picks the cell out of each day's section.
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

/**
 * The stages of a funnel slide, widest first, each with its share of the one
 * above — all of it computed by the backend (`funnel_totals`).
 *
 * Summing a window's days in the browser would be exactly the arithmetic the
 * matrix rule exists to keep out of it, so a page that cannot supply totals
 * gets an empty funnel and says «нет данных» rather than adding up cells.
 */
function funnelSlide(spec, totals) {
  const stages = totals
    ? [
        { name: 'Клики', value: totals.open_count, conversion: null },
        { name: 'Корзины', value: totals.cart_count, conversion: totals.cart_conversion },
        { name: 'Заказы', value: totals.order_count, conversion: totals.order_conversion },
        { name: 'Выкупы', value: totals.buyout_count, conversion: totals.buyout_conversion },
      ].filter((stage) => stage.value > 0)
    : []
  return {
    key: spec.key,
    tab: spec.tab,
    title: spec.title,
    height: FUNNEL_CHART_HEIGHT,
    // No day ribbon and no pinned axis: a funnel has neither.
    axisGutter: 0,
    dayCount: 0,
    funnel: true,
    pickable: false,
    legend: stages.map((stage, index) => ({
      name: stage.name,
      color: SERIES_COLORS[index],
    })),
    empty: !stages.length,
    option: buildFunnelOption(stages),
  }
}

/**
 * Build every chart of the block from the live display matrix.
 *
 * A slide whose series are all blank is kept (its tab must not jump position
 * when a day arrives) and flagged `empty`, so the panel can say «нет данных»
 * instead of drawing an axis around nothing.
 *
 * @param {{days: Array<{iso: string}>, rows: Array, priceRows: Array,
 *   stockRows: Array}} view The store's `matrixView`.
 * @returns {Array<{key: string, tab: string, title: string, empty: boolean,
 *   option: object}>} Empty when the window has no days at all.
 */
export function buildChartSpecs(view, options = {}) {
  return buildSpecs(view, CHART_SPECS, options)
}

/**
 * Turn a list of chart definitions into drawable slides against one matrix.
 *
 * Shared with the account-wide «Графики» page (`aggregateChartSpecs.js`), which
 * draws a SHORTER list from a matrix carrying only «Общая» and «Органика». Both
 * pages therefore go through the same builder, the same theme and the same
 * ribbon geometry, and cannot drift into looking like two different products.
 *
 * @param {object} view A display matrix (the store's `matrixView` shape).
 * @param {Array<object>} specs Chart definitions; see `CHART_SPECS`.
 * @param {{overview?: string[], catalogue?: object}} [options] Which metrics
 *   «Общий» currently shows, and the catalogue to resolve them against — the
 *   aggregate page serves a different set of metrics, so it passes its own.
 * @returns {Array<object>} Slides, or empty when the window has no days.
 */
export function buildSpecs(
  view,
  specs,
  { overview = DEFAULT_OVERVIEW, mode = 'absolute', catalogue = METRICS, totals = null } = {},
) {
  if (!view?.days?.length) return []
  const days = view.days.map((day) => day.iso)

  return specs.map((spec) => {
    // A funnel is the window's totals, not a day series: it has no ribbon, no
    // day axis and no frozen column, so it leaves the shared path here.
    if (spec.funnel) return funnelSlide(spec, totals)
    // «Общий» has no fixed series list — it draws whatever the reader ticked.
    const chosen = spec.pickable
      ? overview
          .slice(0, MAX_OVERVIEW_METRICS)
          .map((key) => catalogue[key])
          .filter(Boolean)
          .map((entry) => ({ ...entry, type: 'line' }))
      : spec.series
    const series = chosen.map((entry, index) => ({
      name: entry.name,
      type: entry.type,
      area: entry.area ?? false,
      colorIndex: entry.colorIndex ?? index,
      unit: entry.unit ?? 'number',
      ...indexed(readSeries(view, entry), spec.pickable && mode === 'index'),
    }))
    return {
      key: spec.key,
      tab: spec.tab,
      title: spec.title,
      // Three stacked panels need more room than one plot; the panel builder
      // lays itself out in percentages, so the pixels have to come from here.
      height: spec.panels ? PANEL_CHART_HEIGHT : CHART_HEIGHT,
      // One axis per unit, so the frozen column grows with the units on show.
      axisGutter: series.length ? gutterFor(series) : AXIS_GUTTER_PX,
      // The picker rides above this slide only.
      pickable: spec.pickable ?? false,
      // The plot is laid out at a fixed width per day and scrolled sideways,
      // so the panel needs to know how many there are.
      dayCount: days.length,
      // Rendered as HTML above the plot rather than on the canvas: a canvas
      // legend scrolls away with the plot it belongs to.
      legend: series.map((entry, index) => ({
        name: entry.name,
        color: SERIES_COLORS[entry.colorIndex ?? index],
      })),
      empty: series.every((entry) => entry.data.every((value) => value == null)),
      option: buildChartOption({
        days,
        stack: spec.stack ?? null,
        panels: spec.panels ?? false,
        // An index is unitless: one axis for everything, whatever was picked.
        indexMode: spec.pickable && mode === 'index',
        series,
      }),
    }
  })
}
