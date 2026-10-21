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
import { formatMoney, formatMoneyFigure, formatNumber, formatPercent } from '@/core/utils/format'

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
 * metrics take a lighter shade of their family's hue — cart conversion is
 * a paler «Корзины» blue, order conversion a paler «Заказы» orange — so a
 * funnel reads as a funnel before the legend is consulted.
 *
 * Keyed by CATALOGUE key, not by metric: `orders` and `orders_organic` read
 * the same backend row and must still be told apart.
 */
export const METRIC_COLORS = {
  // Advertising
  spend: '#1BAF7A', // green — «Затраты»
  views: '#4A3AA7', // violet
  clicks: '#9179E0', // lighter — the same views, but clicked
  ctr: '#EDA100', // yellow
  cpm: '#8E2F4F', // dark cherry — a price of advertising, like CPC
  cpc: '#E34948', // red
  drr_orders: '#C14BAD', // purple
  drr_sales: '#E87BA4', // pink — the same DRR, a different base
  // Funnel
  carts: '#2A78D6', // blue — «Корзины»
  cart_conversion: '#5FA8E8', // lighter — conversion into the same carts
  orders: '#EB6834', // orange — «Заказы»
  order_conversion: '#F2A25C', // lighter — conversion into the same orders
  buyout_percent: '#8A6D3B', // brown
  // General
  seller_price: '#00838F', // teal
  customer_price: '#5B7C99', // grey-blue
  stock_quantity: '#0B7A3B', // dark green — «Остатки»
  stock_total: '#0B7A3B', // the same meaning on the summary page
  order_sum: '#B8471F', // dark orange — the same orders, in money
  orders_organic: '#C98A4B', // «Заказы» without advertising
}

/** A metric outside the map is a bug, but a grey line beats no line. */
const FALLBACK_COLOR = '#6B6B6B'

/** The hue reserved for one catalogue key. */
export function colorForMetric(key) {
  return METRIC_COLORS[key] ?? FALLBACK_COLOR
}

/**
 * Value formatters by the unit a metric measures. Money takes the day's own sign
 * when the series carries one, the series' currency otherwise.
 */
const FORMATTERS = {
  currency: (value, currency, sign) =>
    sign ? formatMoneyFigure(value) + sign : formatMoney(value, currency),
  number: (value) => formatNumber(Math.round(value)),
  percent: formatPercent,
}

/** Tooltip/legend text for one value; `null` reads «нет данных», not «0». */
function formatValue(unit, value, currency, sign) {
  if (value == null || !Number.isFinite(value)) return '—'
  return (FORMATTERS[unit] ?? FORMATTERS.number)(value, currency, sign)
}

/** "2026-07-05" -> "05.07.2026" — what a short window's rotated dates carry. */
export function fullDayLabel(iso) {
  const [year, month, day] = iso.split('-')
  return `${day}.${month}.${year}`
}

/** "2026-07-05" -> "05.07" — the year does not fit 52 weekly labels. */
export function shortDayLabel(iso) {
  const [, month, day] = iso.split('-')
  return `${day}.${month}`
}

/**
 * One series' mark: a column, or a thin line with a dot per day.
 *
 * **Columns only while they fit.** Carts, orders and stock are columns up
 * to {@link BARS_UP_TO_DAYS} and lines past it — a card a year wide would draw
 * 365 of them at 1,5px each, which is a texture rather than a bar. Never
 * stacked: a stack would draw a total in which a cart is a unit of stock.
 *
 * A line is 1,6px with a 3,5px dot rather than 2px and 5px: at a year's density
 * a 5px dot is a bead necklace instead of a day.
 *
 * **Every line carries its own area**, in its own hue at {@link AREA_OPACITY}.
 * One fill was tried first, on the grounds that several translucent ones over
 * each other become mud; at this opacity they do not — where two overlap the
 * tint greys out, which is itself the useful reading ("these two metrics moved
 * together here"), and a plot where only one of five lines has a floor reads as a
 * plot with one important line and four decorations.
 *
 * Lines are smooth. A daily series is a sampling of something continuous, and
 * the straight segments between samples claimed a precision between the days
 * that the data does not have.
 */
function seriesMark(series, color) {
  const shared = {
    name: series.name,
    data: series.data,
    color,
    z: 3,
    // Which ruler this series is read against — see `valueAxes`.
    yAxisIndex: series.axisIndex ?? 0,
  }
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
    smooth: 0.35,
    // Every day gets a dot: on a near-flat series they are what makes one day
    // legibly different from the next, rather than a line that looks straight.
    showSymbol: true,
    symbol: 'circle',
    symbolSize: 3.5,
    emphasis: { scale: 2.4 },
    lineStyle: { width: 1.6 },
    areaStyle: { color, opacity: AREA_OPACITY },
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

/** Ink of the dates: a scale, not a row of headings. */
const DATE_INK = '#8A8A8A'

/**
 * The date axis, in its two weights — and both of them are ROTATED.
 *
 * A horizontal date needs its own full width; a rotated one needs about half.
 * Upright, a month's 31 dates did not fit a card and ECharts printed every
 * second one, which is the worst of both: a daily grid labelled on odd days.
 * At 60° all 31 fit, with the year on them.
 *
 * Past a month even that cannot hold — 31 dates is the limit — so a long window
 * keeps the rotation, drops the year and prints one date per WEEK, which is
 * what makes all 52 of a year fit.
 */
const DAILY_DATE = { color: DATE_INK, fontSize: 9, rotate: 60 }
const WEEKLY_DATE = { color: DATE_INK, fontSize: 9, rotate: 60 }

/**
 * Up to this many days a window is drawn in its SHORT form: a date and an
 * upright per day, and the counts (carts, orders, stock) as columns.
 *
 * A month is what a column needs to stay a column — 31 days across a card is
 * ~35px of slot, and past that they thin to a texture. The date axis changes at
 * the same point, because a 13px date fits about as far as a column does: a
 * window is either short or long, not short for its marks and long for its
 * ruler.
 */
export const BARS_UP_TO_DAYS = 32

/**
 * Opacity of a series' area fill.
 *
 * Low enough that five of them stacked still read as five tints rather than
 * one dark block: where fills overlap the colour greys out, which is what tells
 * the eye the lines are running together there.
 */
const AREA_OPACITY = 0.16

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

/** What the orders ruler falls back to when the window reports no orders. */
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
function valueAxis({
  max = DEFAULT_AXIS_MAX,
  position = 'left',
  color = INK_MUTED,
  rules = true,
  shown = true,
}) {
  return {
    type: 'value',
    position,
    min: 0,
    max,
    interval: ruleStep(max),
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: {
      show: shown,
      // Coloured by the ruler's own first series, which is the only thing that
      // says WHICH lines a second scale belongs to.
      color,
      fontSize: 10,
      hideOverlap: true,
      formatter: (value) => formatNumber(value),
    },
    // Only one axis draws the horizontal rules: two sets of them at different
    // intervals is a grid nothing lines up with.
    splitLine: rules
      ? { lineStyle: { color: GRID_RULE, width: 1, type: [4, 4] } }
      : { show: false },
  }
}

/**
 * Build the plot's rulers: unit counts left, money right, and the index on a scale
 * that is never drawn.
 *
 * The first two are drawn whether or not anything is on them — that is the
 * point of a fixed scale, and an axis that appears and disappears with the
 * selection is what made «Заказы» a readable column one moment and a smear the
 * next. The third carries the unitless series and shows nothing: an index has
 * no unit, so a ruler would have nothing to say, and the hover holds the real
 * value.
 *
 * @param {Array<{max: number|undefined, color: string|undefined, shown: boolean}>} rulers
 *   In axis order — see `metricChart.js#AXES`.
 * @returns {Array<object>} ECharts yAxis configs.
 */
function valueAxes(rulers) {
  if (!rulers.length) return [valueAxis({ max: undefined })]
  return rulers.map((ruler, index) =>
    valueAxis({
      max: ruler.max,
      color: ruler.color,
      position: index === 1 ? 'right' : 'left',
      // The left-hand scale carries the grid; a second set of rules at another
      // interval is a grid nothing lines up with.
      rules: index === 0,
      shown: ruler.shown !== false,
    }),
  )
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
 * Each row is formatted by ITS OWN unit: with «Затраты» beside «ДРР, %» a
 * chart-wide formatter would print one of the two in the other's units.
 *
 * @param {Array<object>} series The built series, in chart order.
 * @param {{index: number|null}} hover Which series the cursor is actually on
 *   (see `focusedPoints`) — a live holder, read at hover time, never a value
 *   baked into the option.
 * @param {string} currency A fallback for money rows whose series names no
 *   `currency` of its own; `''` prints them bare.
 */
function groupedTooltip(series, hover, currency) {
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
        const value = formatValue(
          entry.unit,
          entry.raw ? entry.raw[point.dataIndex] : point.value,
          entry.currency ?? currency,
          entry.signs?.[point.dataIndex],
        )
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
 * cursor anywhere inside the band — most of the plot — arrived as "hovering
 * «Затраты»" and answered with «Затраты» alone. The fill is not a mark, it is the
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
 * Unit counts down the left edge and money down the right, fixed, whatever is
 * ticked; anything that is neither is an index on a scale that is never drawn.
 * See `metricChart.js#AXES`.
 *
 * @param {{days: string[], rulers?: Array<{max: number|undefined, color: string}>,
 *   hover?: object, series: Array<{name: string, unit: string, group?: string,
 *   axisIndex?: number, data: Array<number|null>, raw?: Array<number|null>,
 *   color: string}>, currency?: string}} spec `rulers` are the value scales,
 *   left first; a money series states its own `currency`, and `currency` here
 *   is only the fallback for one that does not.
 */
export function buildChartOption({ days, rulers = [], hover, series, currency = '' }) {
  const weekly = days.length > BARS_UP_TO_DAYS
  const hasBar = series.some((entry) => entry.type === 'bar')
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
    grid: {
      left: AXIS_GUTTER_PX,
      // The right-hand column is reserved whatever is ticked, because the
      // ruler in it is. It is the wider of the two: the money scale is the one
      // that has to fit «1 527 868».
      right: rulers.length > 1 ? AXIS_GUTTER_PX + 20 : 12,
      top: PLOT_TOP,
      bottom: PLOT_BOTTOM,
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: hasBar ? 'shadow' : 'line' },
      backgroundColor: '#FFFFFF',
      borderColor: LINE_SUBTLE,
      borderWidth: 1,
      padding: [8, 12],
      textStyle: { color: INK_PRIMARY, fontSize: 12 },
      formatter: groupedTooltip(series, hover, currency),
    },
    xAxis: {
      type: 'category',
      data: days.map(weekly ? shortDayLabel : fullDayLabel),
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
    yAxis: valueAxes(rulers),
    series: series.map((entry) => seriesMark(entry, entry.color)),
  }
}
