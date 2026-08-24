/**
 * The shared look of every monitoring chart: palette, axes, grid, tooltip.
 *
 * Split from `metricChart.js` so the WHAT (which metrics a page can offer) and
 * the HOW (what a chart looks like) stay separately readable — that file is a
 * catalogue, this one is the theme.
 *
 * Ink and surface mirror `tailwind.config.js` (text-muted, text-primary,
 * border-subtle, bg-surface). They are repeated as hex because ECharts paints
 * onto a canvas and cannot resolve a Tailwind class; when a token moves, it
 * moves here too.
 */
import { formatCurrency, formatNumber, formatPercent } from '@/core/utils/format'

/** Tailwind `textColor.muted` / `textColor.primary` / `border.subtle`. */
const INK_MUTED = '#858585'
const INK_PRIMARY = '#101010'
const LINE_SUBTLE = '#E0E0E0'

/**
 * Gridline ink — deliberately darker than `border.subtle`.
 *
 * The subtle border is right for the edge of a card, where the line is only
 * saying «this block ends». A gridline is read ACROSS the plot to place a mark
 * against a number, and at #E0E0E0 on #F1F1F1 it disappeared a few pixels from
 * the axis.
 */
const LINE_GRID = '#BFBFBF'

/**
 * One hue per METRIC, fixed for the life of the app.
 *
 * Colour used to be handed out by slot: the first metric ticked took blue, the
 * second orange. That made the same metric a different colour on every visit —
 * «Заказы» blue on one reading of the page and orange on the next — so the
 * legend had to be re-read every time and two screenshots of the same card
 * could not be compared.
 *
 * The four the reader named are fixed by meaning: «Затраты» and «Остатки» are
 * the two greens, «Корзины» blue, «Заказы» orange. Around those, related
 * metrics take a lighter shade of their family's hue — конверсия в корзину is
 * a paler «Корзины» blue, конверсия в заказ a paler «Заказы» orange — so a
 * funnel reads as a funnel before the legend is consulted.
 *
 * Keyed by CATALOGUE key, not by metric: `orders` and `orders_organic` read
 * the same backend row and must still be told apart.
 */
export const METRIC_COLORS = {
  // Реклама
  spend: '#1BAF7A', // зелёный — «Затраты»
  views: '#4A3AA7', // фиолетовый
  clicks: '#9179E0', // светлее — те же показы, но кликнутые
  ctr: '#EDA100', // жёлтый
  cpm: '#8E2F4F', // тёмно-вишнёвый — цена рекламы, как и CPC
  cpc: '#E34948', // красный
  drr_orders: '#C14BAD', // пурпурный
  drr_sales: '#E87BA4', // розовый — тот же ДРР, другая база
  // Воронка
  carts: '#2A78D6', // синий — «Корзины»
  cart_conversion: '#5FA8E8', // светлее — конверсия в те же корзины
  orders: '#EB6834', // оранжевый — «Заказы»
  order_conversion: '#F2A25C', // светлее — конверсия в те же заказы
  buyout_percent: '#8A6D3B', // коричневый
  // Общие
  seller_price: '#00838F', // бирюзовый
  customer_price: '#5B7C99', // серо-синий
  stock_quantity: '#0B7A3B', // тёмно-зелёный — «Остатки»
  stock_total: '#0B7A3B', // тот же смысл на сводной странице
  order_sum: '#B8471F', // тёмно-оранжевый — те же заказы, в рублях
  orders_organic: '#C98A4B', // «Заказы» без рекламы
}

/** A metric outside the map is a bug, but a grey line beats no line. */
const FALLBACK_COLOR = '#6B6B6B'

/** The hue reserved for one catalogue key. */
export function colorForMetric(key) {
  return METRIC_COLORS[key] ?? FALLBACK_COLOR
}

/** Value formatters by the unit a metric measures. */
const FORMATTERS = {
  currency: formatCurrency,
  number: (value) => formatNumber(Math.round(value)),
  percent: formatPercent,
}

/** Tooltip/legend text for one value; `null` reads «нет данных», not «0». */
function formatValue(unit, value) {
  if (value == null || !Number.isFinite(value)) return '—'
  return (FORMATTERS[unit] ?? FORMATTERS.number)(value)
}

/** "2026-07-05" -> "05.07" — the full year would not fit 30 columns. */
export function shortDayLabel(iso) {
  const [, month, day] = iso.split('-')
  return `${day}.${month}`
}

/** One series' mark spec: 2px lines, rounded bar ends, its own fixed hue. */
function seriesMark(series, color, dayWidth) {
  const shared = { name: series.name, data: series.data, color, z: 3 }
  if (series.type === 'bar') {
    return {
      ...shared,
      type: 'bar',
      itemStyle: { borderRadius: [4, 4, 0, 0] },
      barMaxWidth: Math.round(dayWidth * BAR_WIDTH_RATIO),
    }
  }
  return {
    ...shared,
    type: 'line',
    smooth: false,
    // Every day gets a dot. The plot is laid out at a fixed width PER DAY and
    // scrolled (see `DAY_WIDTH`), so there is always room for them — and on a
    // near-flat series they are what makes one day legibly different from the
    // next, rather than a line that looks straight.
    showSymbol: true,
    symbol: 'circle',
    symbolSize: 5,
    emphasis: { scale: 1.8 },
    lineStyle: { width: 2 },
    // Without this a line only answers a hover on one of its DOTS — the path
    // between them is inert, and «hovering this line» is a 5px target twenty
    // times a window rather than the line the reader is pointing at.
    triggerLineEvent: true,
    // A gap in the data is a day WB served nothing — joining across it would
    // draw a trend that never happened.
    connectNulls: false,
  }
}

/**
 * Plot geometry, in pixels and shared by both copies of a chart (see
 * `axisOnlyOption`). `PLOT_BOTTOM` is the strip the day labels sit in.
 */
const PLOT_TOP = 12
const PLOT_BOTTOM = 30

/** Width of the pinned y-axis column, wide enough for «12 000». */
export const AXIS_GUTTER_PX = 74

/**
 * Width per day — the plot is laid out at a fixed one and scrolled sideways.
 *
 * Squeezing a month into the card is what made the charts unreadable in the
 * first place: at ~24px a day two bars have no room to be two bars, and a
 * line's daily moves are sub-pixel. 72px holds three grouped columns with air
 * between the days, which is what the chart is actually asked to carry, since
 * остатки, корзины and заказы stand side by side rather than stacking.
 *
 * A quarter is a different question, though. Past two months the reader is
 * looking for a trend rather than reading Tuesday against Wednesday, and 90
 * days at 72px is six screens of ribbon to drag through to see one. So a long
 * window tightens to 44px — still two and a half columns wide, and it fits
 * about two thirds more days in the card at once.
 *
 * One step, not a curve: a width that slid with the day count would redraw the
 * whole plot at a new scale every time the calendar moved by a day.
 */
export const DAY_WIDTH_PX = 72
const DENSE_DAY_WIDTH_PX = 44
const DENSE_FROM_DAYS = 60

/** How wide one day is drawn in a window of `dayCount` days. */
export function dayWidthFor(dayCount) {
  return dayCount >= DENSE_FROM_DAYS ? DENSE_DAY_WIDTH_PX : DAY_WIDTH_PX
}

/**
 * A column's cap as a share of its day, so the bars tighten with the ribbon.
 *
 * Left at a fixed 28px, a dense window would draw three 28px columns into 44px
 * of day: they would touch their neighbours and the day boundaries would stop
 * being visible, which is the one thing the tighter layout must not cost.
 */
const BAR_WIDTH_RATIO = 0.39

/** What the orders ruler falls back to when the window reports no заказы. */
export const DEFAULT_AXIS_MAX = 500

/**
 * Round a value up to a readable top tick — 430 -> 450, 512 -> 550, 12 -> 15.
 *
 * Half a power of ten is the step, so the ceiling lands on a number a reader
 * recognises as round without ECharts printing «481 900,432» at the top of the
 * scale.
 */
export function niceCeiling(value) {
  if (!Number.isFinite(value) || value <= 0) return DEFAULT_AXIS_MAX
  const step = 10 ** Math.floor(Math.log10(value)) / 2
  return Math.ceil(value / step) * step
}

/**
 * The single value axis: a ruler of ЗАКАЗОВ, and nothing else.
 *
 * Every series is drawn as an index (see `metricChart.js`), so no axis can be
 * true for all of them at once and a scale that re-fitted itself to whatever
 * was ticked told the reader nothing — the same line landed at a different
 * height on every visit. The scale is therefore anchored to one quantity the
 * page is actually about, заказы per day, and carries no unit name: the numbers
 * are заказы, the marks are shapes, and the hover holds the real values.
 */
function ordersAxis(max) {
  return {
    type: 'value',
    min: 0,
    max,
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: {
      color: INK_MUTED,
      fontSize: 11,
      hideOverlap: true,
      formatter: (value) => formatNumber(value),
    },
    splitLine: { lineStyle: { color: LINE_GRID, width: 1.5, type: [6, 4] } },
  }
}

/**
 * A tooltip whose rows are grouped the way the picker above it is grouped.
 *
 * Once five or six metrics are on one plot the hover is a list, and a list of
 * six unlike numbers is read by hunting. «Реклама», «Воронка» and «Общие» are
 * where the reader already looks for a metric — repeating that split here,
 * with the same titles and a dotted rule between them, means the eye lands in
 * the right third before it reads a single number.
 *
 * Each row is formatted by ITS OWN unit: with «Затраты, ₽» beside «ДРР, %» a
 * chart-wide formatter would print one of the two in the other's units.
 *
 * @param {Array<object>} series The built series, in chart order.
 * @param {{index: number|null}} hover Which series the cursor is actually on
 *   (see `focusedPoints`) — a live holder, read at hover time, never a value
 *   baked into the option.
 */
function groupedTooltip(series, hover) {
  return (params) => {
    const points = focusedPoints(
      [...params].sort((a, b) => a.seriesIndex - b.seriesIndex),
      hover,
    )
    let lastGroup = null
    const rows = points
      .map((point) => {
        const entry = series[point.seriesIndex] ?? {}
        // What the hover is FOR: the plotted number is a shape, so the row
        // shows the quantity underneath it. Only that — the index was on the
        // canvas already, and printing it again in brackets on every row was a
        // second column of numbers nobody was reading.
        const value = formatValue(entry.unit, entry.raw ? entry.raw[point.dataIndex] : point.value)
        const heading =
          entry.group && entry.group !== lastGroup
            ? `<div style="${lastGroup ? `border-top:1px dotted ${LINE_GRID};margin-top:6px;` : ''}` +
              `padding-top:${lastGroup ? '6px' : '0'};color:${INK_MUTED};font-size:11px">` +
              `${entry.group}</div>`
            : ''
        lastGroup = entry.group ?? lastGroup
        return (
          heading +
          `<div style="display:flex;gap:24px;justify-content:space-between">` +
          `<span>${point.marker}${point.seriesName}</span><b>${value}</b></div>`
        )
      })
      .join('')
    return `<div style="color:${INK_MUTED};margin-bottom:4px">${params[0].axisValue}</div>` + rows
  }
}

/**
 * Narrow a day's points to the one the cursor is actually on.
 *
 * A hover over the whole day is a question about the day and answers with
 * every metric. A hover that lands ON a line or a column is a question about
 * THAT metric, and answering it with five others is the reader doing the
 * filtering the chart could have done. The exception is a crossing: when two
 * metrics plot at the same point there is no telling which one was aimed at,
 * so both are shown.
 *
 * @param {Array<object>} points The day's points, series-ordered.
 * @param {{index: number|null}} [hover] The series under the cursor, if any.
 */
export function focusedPoints(points, hover) {
  const focus = hover?.index
  if (focus == null) return points
  const focused = points.find((point) => point.seriesIndex === focus)
  if (!focused) return points
  const crossing = points.filter((point) => point.value === focused.value)
  return crossing.length ? crossing : [focused]
}

/**
 * The same chart with its y axis muted — the copy that scrolls.
 *
 * Its labels belong to the pinned copy standing to its left; drawn here too
 * they would scroll away mid-ribbon and collide with the data on the way out.
 *
 * @param {object} option A built chart option.
 * @returns {object} The same option, minus the y-axis furniture.
 */
export function plotOnlyOption(option) {
  const muted = (axis) => ({ ...axis, axisLabel: { ...axis.axisLabel, show: false }, name: '' })
  return {
    ...option,
    yAxis: Array.isArray(option.yAxis) ? option.yAxis.map(muted) : muted(option.yAxis),
  }
}

/**
 * The same chart, reduced to its y axis — the frozen column of a scrolling plot.
 *
 * The plot is drawn at a fixed width per day and scrolled sideways, which took
 * the y axis off screen with it: gridlines survived, the numbers did not. So
 * the chart is rendered TWICE, side by side — this copy pinned at the card's
 * left edge showing only the axis, the wide one scrolling beside it with its
 * own labels switched off.
 *
 * The two agree without any extent arithmetic here, and that is the point of
 * doing it this way: an axis extent is a pure function of the DATA and the axis
 * config, neither of which depends on how wide the canvas is. Give both copies
 * the same series, the same height and the same grid top/bottom, and ECharts
 * independently arrives at the same ticks in the same places. The series are
 * kept (invisible) for exactly that reason — dropping them would drop the
 * extent with them.
 *
 * @param {object} option A built chart option.
 * @returns {object} The same option, stripped to the axis.
 */
export function axisOnlyOption(option, gutter = AXIS_GUTTER_PX) {
  const mapAxis = (axis, fn) => (Array.isArray(axis) ? axis.map(fn) : fn(axis))
  return {
    ...option,
    animation: false,
    tooltip: { show: false },
    // The gutter is the whole canvas here, so the grid is pushed to its right
    // edge and the labels render in the space to the left of it.
    grid: mapAxis(option.grid, (grid) => ({ ...grid, left: gutter - 6, right: 0 })),
    xAxis: mapAxis(option.xAxis, (axis) => ({
      ...axis,
      axisLabel: { ...axis.axisLabel, show: false },
      axisLine: { show: false },
      splitLine: { show: false },
    })),
    yAxis: mapAxis(option.yAxis, (axis) => ({ ...axis, splitLine: { show: false } })),
    // Present in the data, absent on screen: they set the extent and draw
    // nothing. `silent` keeps them from answering a hover that is not theirs.
    series: option.series.map((entry) => ({
      ...entry,
      silent: true,
      showSymbol: false,
      lineStyle: { ...entry.lineStyle, opacity: 0 },
      itemStyle: { ...entry.itemStyle, opacity: 0, borderWidth: 0 },
    })),
  }
}

/**
 * A complete ECharts option for one chart.
 *
 * One axis, always: every series is an index, so a second scale would be a
 * second ruler for the same unitless numbers.
 *
 * @param {{days: string[], axisMax: number, hover?: object,
 *   series: Array<{name: string, type: string, unit: string, group?: string,
 *   data: Array<number|null>, raw?: Array<number|null>, color: string}>}} spec
 */
export function buildChartOption({ days, axisMax = DEFAULT_AXIS_MAX, hover, series }) {
  const hasBar = series.some((entry) => entry.type === 'bar')
  // Derived here rather than passed in, so the pinned axis copy and the
  // scrolling copy cannot disagree about how wide a day is.
  const dayWidth = dayWidthFor(days.length)

  return {
    animationDuration: 300,
    // A fixed allowance under the plot for the day labels and the scroll
    // handle. Explicit pixels, NOT `containLabel`: this plot is rendered twice
    // — once wide inside the scroller and once as a narrow pinned axis beside
    // it — and `containLabel` sizes the grid around whichever labels each copy
    // happens to show, which would slide the two apart vertically by a few
    // pixels and leave every gridline off by that much.
    grid: { left: 0, right: 8, top: PLOT_TOP, bottom: PLOT_BOTTOM },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: hasBar ? 'shadow' : 'line' },
      backgroundColor: '#FFFFFF',
      borderColor: LINE_SUBTLE,
      borderWidth: 1,
      padding: [8, 12],
      textStyle: { color: INK_PRIMARY, fontSize: 12 },
      formatter: groupedTooltip(series, hover),
    },
    xAxis: {
      type: 'category',
      data: days.map(shortDayLabel),
      boundaryGap: hasBar,
      axisLine: { lineStyle: { color: LINE_SUBTLE } },
      axisTick: { show: false },
      // The date is what every other number on the row is about, so it is read
      // first and sized for it — not the smallest type on the canvas.
      axisLabel: { color: INK_PRIMARY, fontSize: 13, fontWeight: 600, hideOverlap: true },
      // Solid uprights between the days, to go with the dashed horizontals:
      // at 72px a day the columns of one date drift a long way from its label.
      splitLine: { show: true, lineStyle: { color: LINE_SUBTLE, width: 1 } },
    },
    yAxis: ordersAxis(axisMax),
    series: series.map((entry) => seriesMark(entry, entry.color, dayWidth)),
  }
}
