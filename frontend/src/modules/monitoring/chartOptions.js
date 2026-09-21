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

/**
 * One series' mark: a column, or a thin line with a dot per day.
 *
 * **Columns only while they fit.** Корзины, заказы and остатки are columns up
 * to {@link BARS_UP_TO_DAYS} and lines past it — a card a year wide would draw
 * 365 of them at 1,5px each, which is a texture rather than a bar. Never
 * stacked: a stack would draw a total in which a cart is a unit of stock.
 *
 * A line is 1,6px with a 3,5px dot rather than 2px and 5px: at a year's density
 * a 5px dot is a bead necklace instead of a day.
 *
 * `filled` gets the area under it — at most one series ever does, and it is the
 * first LINE in the pick, since a column has no area to fill. It is what tells
 * the eye where the bottom of the plot is; two translucent fills over each
 * other stop being a fill and become mud.
 *
 * It is drawn whether or not the plot is an index. The area under an index is
 * not a quantity, and that was once reason enough to withhold it; what the
 * argument missed is that the fill is not a measurement in the first place.
 */
function seriesMark(series, color, filled) {
  const shared = { name: series.name, data: series.data, color, z: 3 }
  if (series.type === 'bar') {
    return {
      ...shared,
      type: 'bar',
      itemStyle: { borderRadius: [3, 3, 0, 0] },
      // A share of the day's own slot, so the columns tighten with the window
      // instead of touching their neighbours once a month is on screen.
      barMaxWidth: '70%',
    }
  }
  return {
    ...shared,
    type: 'line',
    smooth: false,
    // Every day gets a dot: on a near-flat series they are what makes one day
    // legibly different from the next, rather than a line that looks straight.
    showSymbol: true,
    symbol: 'circle',
    symbolSize: 3.5,
    emphasis: { scale: 2.4 },
    lineStyle: { width: 1.6 },
    ...(filled ? { areaStyle: { color, opacity: AREA_OPACITY } } : {}),
    // Without this a line only answers a hover on one of its DOTS — the path
    // between them is inert, and «hovering this line» is a 5px target twenty
    // times a window rather than the line the reader is pointing at.
    triggerLineEvent: true,
    // A gap in the data is a day WB served nothing — joining across it would
    // draw a trend that never happened.
    connectNulls: false,
  }
}

/** Plot geometry. `PLOT_BOTTOM` is the strip the dates sit in, rotated or not. */
const PLOT_TOP = 12
const PLOT_BOTTOM = 54

/** Width of the y-axis column, wide enough for «12 000». */
export const AXIS_GUTTER_PX = 74

/** Ink of the weekly uprights, and of the horizontal rules. */
const GRID_UPRIGHT = '#E8E8E8'
const GRID_RULE = '#D9D9D9'

/**
 * The date axis, in its two weights.
 *
 * Up to a month every day gets its own date, read straight. 11px is what fits
 * 31 of them across a card now that the window is not scrolled: at 13px
 * `hideOverlap` dropped every second one, and a month labelled on odd days is
 * harder to read than a month labelled small.
 *
 * Past a month that cannot hold — 13px bold dates fit about once a fortnight,
 * so the plot read as a fortnightly scale while the uprights under it were
 * weekly. So a long window drops to a date per WEEK at 9px and 60°, which is
 * what makes all 52 of a year fit.
 */
const DAILY_DATE = { color: INK_PRIMARY, fontSize: 11, fontWeight: 600 }
const WEEKLY_DATE = { color: '#8A8A8A', fontSize: 9, rotate: 60 }

/**
 * Up to this many days a window is drawn in its SHORT form: a date and an
 * upright per day, and the counts (корзины, заказы, остатки) as columns.
 *
 * A month is what a column needs to stay a column — 31 days across a card is
 * ~35px of slot, and past that they thin to a texture. The date axis changes at
 * the same point, because a 13px date fits about as far as a column does: a
 * window is either short or long, not short for its marks and long for its
 * ruler.
 */
export const BARS_UP_TO_DAYS = 32

/** Opacity of the leading series' area fill. */
const AREA_OPACITY = 0.22

/**
 * The window's weeks, Monday-first — the division the axis is drawn on.
 *
 * A day is what everything else on the page is read at, so every point stays
 * daily; what a long window needs is somewhere to stand, and the week is it.
 *
 * `Date.UTC` via the ISO string: a local-time parse shifts the day back an hour
 * east of Greenwich and puts every Monday in the previous week.
 *
 * @param {string[]} days ISO days, oldest first.
 * @returns {Set<number>} Indexes of the days that open a week. The first one is
 *   always included, whatever weekday the window happens to begin on.
 */
export function weekStarts(days) {
  const starts = new Set()
  days.forEach((iso, index) => {
    const weekday = (new Date(`${iso}T00:00:00Z`).getUTCDay() + 6) % 7
    if (weekday === 0 || !index) starts.add(index)
  })
  return starts
}

/** How many rules the plot carries between the baseline and the top. */
const RULE_COUNT = 4

/** The gaps a reader recognises, per power of ten. */
const NICE_STEPS = [1, 2, 5, 10]

/**
 * A readable gap between two horizontal rules — 1, 2 or 5 times a power of ten.
 *
 * The scale stops at the data's own maximum rather than at a rounded ceiling
 * above it (a ruler stopping at 80 for a 69 spends a fifth of the canvas on
 * nothing), so the step cannot be a quarter of a round number: `283 / 4` is
 * 70,75 and a rule at 70,75 is a number nobody reads. Rounding the STEP puts
 * the rules on 0, 100, 200 and leaves the odd number where it belongs — at the
 * top, where it is the one fact the axis is reporting.
 *
 * @param {number} top The largest value plotted.
 * @returns {number} The gap between rules.
 */
export function ruleStep(top) {
  const rough = top / RULE_COUNT
  const power = 10 ** Math.floor(Math.log10(rough))
  const scaled = rough / power
  // NEAREST of the four, measured in ratio rather than in difference — a step
  // rounded up every time draws two rules where four were asked for, and 1,07
  // is much closer to 1 than to 2 however it is written.
  const nice = NICE_STEPS.reduce((best, candidate) =>
    Math.abs(Math.log10(scaled / candidate)) < Math.abs(Math.log10(scaled / best))
      ? candidate
      : best,
  )
  return nice * power
}

/** What the orders ruler falls back to when the window reports no заказы. */
export const DEFAULT_AXIS_MAX = 500

/**
 * The single value axis, topping out at what was actually plotted.
 *
 * It used to round up to a «nice» ceiling above the data, which spent a fifth
 * of the canvas on empty air; the rules are put on round numbers by
 * {@link ruleStep} instead, and the top of the scale is left as the one odd
 * number the axis is there to report.
 *
 * It carries no unit name. When every picked metric shares a unit the numbers
 * are that unit; when the pick is mixed they are an index, and the hover holds
 * the real values either way — see `metricChart.js`.
 */
function valueAxis(max) {
  return {
    type: 'value',
    min: 0,
    max,
    ...(max ? { interval: ruleStep(max) } : {}),
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: {
      color: INK_MUTED,
      fontSize: 10,
      hideOverlap: true,
      formatter: (value) => formatNumber(value),
    },
    splitLine: { lineStyle: { color: GRID_RULE, width: 1, type: [4, 4] } },
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
 * How close to a mark the cursor has to be for the hover to be about it.
 *
 * The filled area belongs to its series as far as ECharts is concerned, so a
 * cursor anywhere inside the band — most of the plot — arrived as «наведён на
 * Затраты» and answered with Затраты alone. The fill is not a mark, it is the
 * floor; a question about one metric is asked by pointing at the metric.
 */
const MARK_REACH_PX = 14

/**
 * Is the cursor ON a series' mark, or merely somewhere inside its fill?
 *
 * @param {{subType?: string, cursorY?: number|null, markY?: number|null}} where
 *   `subType` is ECharts' `componentSubType`; `markY` is the pixel the series'
 *   own point for that day sits at.
 * @returns {boolean} A column is its whole height and has no fill to be
 *   confused with, so it always counts. Otherwise the cursor has to be within
 *   {@link MARK_REACH_PX} of the point. **Unknown counts as «no»**: ECharts
 *   reports an area hover with no value at all, so «cannot tell» and «in the
 *   fill» are the same case, and the day's full list answers both.
 */
export function isOnMark({ subType, cursorY, markY }) {
  if (subType === 'bar') return true
  if (cursorY == null || markY == null) return false
  return Math.abs(cursorY - markY) <= MARK_REACH_PX
}

/**
 * Narrow a day's points to the one the cursor is actually on.
 *
 * A hover over the whole day is a question about the day and answers with
 * every metric. A hover that lands ON a dot, a line or a column (see
 * {@link isOnMark}) is a question about THAT metric, and answering it with five others is the reader doing the
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
 * A complete ECharts option for one chart.
 *
 * The whole window on the card's own width — no ribbon, no second copy of the
 * plot with a pinned axis beside it. That layout existed because the plot was
 * drawn at a fixed width per day and scrolled sideways, which is right for a
 * fortnight and wrong for a year: 365 days at 44px is nine metres to drag
 * through, and the shape a reader came for is never on screen at once.
 *
 * One axis, always. A second scale would be a second ruler for numbers that
 * already share one — see `metricChart.js` for when those numbers are the
 * metrics themselves and when they are an index.
 *
 * @param {{days: string[], axisMax?: number, hover?: object,
 *   series: Array<{name: string, unit: string, group?: string,
 *   data: Array<number|null>, raw?: Array<number|null>, color: string}>}} spec
 */
export function buildChartOption({ days, axisMax = DEFAULT_AXIS_MAX, hover, series }) {
  const weekly = days.length > BARS_UP_TO_DAYS
  const hasBar = series.some((entry) => entry.type === 'bar')
  // The fill belongs to the first LINE, not the first series: with корзины
  // ticked first the leading entry is a column, which has no area.
  const fillIndex = series.findIndex((entry) => entry.type !== 'bar')
  const starts = weekStarts(days)
  // Every day up to a month, every week past it — for the dates AND for the
  // uprights, so a label always has an upright under it.
  // `0` is «every category», not «auto»: ECharts' own auto step is computed
  // from the axis length and is conservative enough to print a month on odd
  // days. `hideOverlap` below still thins them if the card is genuinely too
  // narrow, which is the behaviour actually wanted.
  const tick = weekly ? (index) => starts.has(index) : 0

  return {
    animationDuration: 300,
    // Explicit pixels rather than `containLabel`: the bottom strip has to hold
    // a date rotated to {@link DATE_ROTATE}, and the left one a five-figure
    // number, whether or not this particular window happens to have either.
    grid: { left: AXIS_GUTTER_PX, right: 12, top: PLOT_TOP, bottom: PLOT_BOTTOM },
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
      // Lines close their area against the origin; columns need the half-slot
      // either side, or the first and last of them are cut in half by the grid.
      boundaryGap: hasBar,
      axisLine: { lineStyle: { color: LINE_SUBTLE } },
      axisTick: { show: false },
      // A date per week, not per day: at a year's width a label per day is an
      // inkblot. `hideOverlap` thins them further on a narrow card.
      axisLabel: { ...(weekly ? WEEKLY_DATE : DAILY_DATE), hideOverlap: true, interval: tick },
      // The uprights carry the same division as the dates, and they stay
      // whatever `hideOverlap` does to those — the scale has to survive a card
      // too narrow to print every one of them.
      splitLine: {
        show: true,
        interval: tick,
        lineStyle: { color: weekly ? GRID_UPRIGHT : LINE_SUBTLE, width: 1 },
      },
    },
    yAxis: valueAxis(axisMax),
    series: series.map((entry, index) => seriesMark(entry, entry.color, index === fillIndex)),
  }
}
