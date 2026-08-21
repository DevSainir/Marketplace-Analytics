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
import { AXIS_GUTTER_PX, SERIES_COLORS, buildChartOption } from '@/modules/monitoring/chartOptions'

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

/** Every ad bucket of one metric as a stacked series list, plus «Органика». */
const byAdBucket = (metric, { organic = false } = {}) => [
  ...(organic ? [{ ...ORGANIC, metric, type: 'bar' }] : []),
  ...AD_BUCKETS.map((entry) => ({ ...entry, metric, type: 'bar' })),
]

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
/** Shared by both «Воронка» tabs — the same numbers, drawn two ways. */
const FUNNEL_SERIES = [
  { metric: 'clicks', bucket: 'total', name: 'Клики', type: 'line' },
  { metric: 'carts', bucket: 'total', name: 'Корзины', type: 'line' },
  { metric: 'orders', bucket: 'total', name: 'Заказы', type: 'line' },
]

const CHART_SPECS = [
  {
    key: 'sales',
    tab: 'Продажи',
    title: 'Заказы и выкупы, ₽',
    unit: 'currency',
    // «Затраты, ₽» is the same unit but an order of magnitude smaller — on this
    // scale its line sits flat on the axis and reads as zero every day. It gets
    // the «Расходы» slide, whose stack totals the very same number.
    series: [
      { metric: 'order_sum', bucket: 'total', name: 'Заказы, ₽', type: 'bar' },
      { metric: 'buyout_sum', bucket: 'total', name: 'Выкупы, ₽', type: 'bar' },
    ],
  },
  {
    key: 'drr',
    tab: 'ДРР',
    title: 'Доля рекламных расходов, %',
    unit: 'percent',
    series: [
      { metric: 'drr_orders', bucket: 'total', name: 'ДРР от заказов, %', type: 'line' },
      { metric: 'drr_sales', bucket: 'total', name: 'ДРР от продаж, %', type: 'line' },
    ],
  },
  {
    key: 'funnel',
    tab: 'Воронка 1',
    title: 'Клики → корзины → заказы, шт',
    unit: 'number',
    // One plot, ONE absolute scale, three lines on it. Заказы therefore run low
    // and flat under клики — which is the truth about a funnel, and the reason
    // «Воронка 2» exists beside it: a scale per stage there shows each one's own
    // shape, this one shows how the three actually compare.
    series: FUNNEL_SERIES,
  },
  {
    key: 'funnel_panels',
    tab: 'Воронка 2',
    title: 'Клики → корзины → заказы, шт',
    unit: 'number',
    // The same three series as one panel each, with their own plain axes. The
    // lines cannot cross here — which in a funnel matters, because
    // клики >= корзины >= заказы always holds and a crossing is always false.
    panels: true,
    series: FUNNEL_SERIES,
  },
  {
    key: 'conversion',
    tab: 'Конверсии',
    title: 'Конверсии и выкуп, %',
    unit: 'percent',
    series: [
      { metric: 'cart_conversion', bucket: 'total', name: 'В корзину, %', type: 'line' },
      { metric: 'order_conversion', bucket: 'total', name: 'В заказ, %', type: 'line' },
      { metric: 'buyout_percent', bucket: 'total', name: 'Выкуп, %', type: 'line' },
    ],
  },
  {
    key: 'spend_mix',
    tab: 'Расходы',
    title: 'Затраты по типам трафика, ₽',
    unit: 'currency',
    stack: 'spend',
    series: byAdBucket('spend'),
  },
  {
    key: 'orders_mix',
    tab: 'Реклама и органика',
    title: 'Заказы: реклама и органика, шт',
    unit: 'number',
    stack: 'orders',
    series: byAdBucket('orders', { organic: true }),
  },
  {
    key: 'price',
    tab: 'Цены',
    title: 'Цена продавца и покупателя, ₽',
    unit: 'currency',
    source: 'priceRows',
    series: [
      { metric: 'seller_price', name: 'Цена продавца, ₽', type: 'line' },
      { metric: 'customer_price', name: 'Цена покупателя, ₽', type: 'line' },
    ],
  },
  {
    key: 'stock',
    tab: 'Остатки',
    title: 'Остаток и товар в пути, шт',
    unit: 'number',
    stack: 'stock',
    source: 'stockRows',
    series: [
      { metric: 'stock_quantity', name: 'На складах', type: 'line', area: true },
      { metric: 'stock_to_client', name: 'В пути к клиенту', type: 'line', area: true },
      { metric: 'stock_from_client', name: 'В пути от клиента', type: 'line', area: true },
    ],
  },
]

/**
 * The per-day values of one metric row, read straight out of the display
 * matrix's cells — a lookup, not a computation.
 *
 * Mini-block rows (`priceRows`/`stockRows`) already carry one cell per day;
 * the main grid is day-major with a `COLUMNS_PER_DAY` stride, so the bucket's
 * column index picks the cell out of each day's section.
 */
function readSeries(view, spec, series) {
  const rows = view[spec.source ?? 'rows'] ?? []
  const row = rows.find((candidate) => candidate.key === series.metric)
  if (!row) return view.days.map(() => null)
  if (spec.source) return row.cells.map((cell) => cell.raw ?? null)

  const column = BUCKET_INDEX.get(series.bucket)
  if (column === undefined) return view.days.map(() => null)
  return view.days.map((_, day) => row.cells[day * COLUMNS_PER_DAY + column]?.raw ?? null)
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
export function buildChartSpecs(view) {
  if (!view?.days?.length) return []
  const days = view.days.map((day) => day.iso)

  return CHART_SPECS.map((spec) => {
    const series = spec.series.map((entry, index) => ({
      name: entry.name,
      type: entry.type,
      area: entry.area ?? false,
      colorIndex: entry.colorIndex ?? index,
      data: readSeries(view, spec, entry),
    }))
    return {
      key: spec.key,
      tab: spec.tab,
      title: spec.title,
      // Three stacked panels need more room than one plot; the panel builder
      // lays itself out in percentages, so the pixels have to come from here.
      height: spec.panels ? PANEL_CHART_HEIGHT : CHART_HEIGHT,
      axisGutter: AXIS_GUTTER_PX,
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
        unit: spec.unit,
        stack: spec.stack ?? null,
        panels: spec.panels ?? false,
        series,
      }),
    }
  })
}
