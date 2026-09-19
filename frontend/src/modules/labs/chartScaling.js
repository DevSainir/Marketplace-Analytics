/**
 * SANDBOX — the metrics chart on a long window, drawn the way the reference is.
 *
 * The live chart is laid out at a fixed width PER DAY and scrolled sideways.
 * That is right for a fortnight and wrong for a year: 365 days at 44px is nine
 * metres of ribbon, and the shape a reader came for — «когда это началось» —
 * is never on screen at once. This one drops the ribbon: one plot, the card's
 * own width, every day of the window in it.
 *
 * **No columns, at any window length.** Folding them into weeks was tried and
 * rejected: a weekly column is a different quantity from the daily numbers
 * beside it, and reading one against the other is the mistake the chart would
 * be inviting. Everything is a line, every line keeps a point per day, and the
 * only thing that is weekly is the RULER — an upright and a date at each week
 * start, which is what makes a year's worth of days locatable.
 *
 * The rest of this module is the reference's own drawing, copied deliberately
 * rather than approximated. Five things separate it from what we had, and all
 * five are why ours looked heavy:
 *
 * 1. **A filled area under the leading line.** It is what gives the plot a
 *    baseline to read heights against. Only the leading one is filled — two
 *    translucent fills over each other stop being a fill and become mud.
 * 2. **Thin lines and small dots.** 1.6px and a 3.5px circle, against 2px and
 *    5px. At 365 points a 5px dot is a bead necklace; at 3.5px it is a day.
 * 3. **Dates rotated and small.** 13px bold horizontal dates fit once a
 *    fortnight and read as headings. 9px at 60° fits every week and reads as a
 *    scale, which is all a date axis is.
 * 4. **The top of the scale is the data's own maximum**, not a rounded ceiling
 *    above it. The reference tops out at its own 67; a scale that stops at 80
 *    spends a fifth of the canvas on nothing.
 * 5. **Metrics that share a unit are drawn as they are**, not rebased to 100 —
 *    see {@link sharesOneUnit}. The index is for a mixed pick and was being
 *    applied to every pick, which drew корзины as an index against заказы as a
 *    count and started one of the two at exactly 100 on the left edge.
 */
import { AXIS_GUTTER_PX, buildChartOption, shortDayLabel } from '@/modules/labs/chartOptions'
import { indexed, metricSeriesSpecs } from '@/modules/labs/metricChart'

/**
 * What the long-window chart opens on.
 *
 * Two series, not the live chart's five. A year of days is already a dense
 * canvas; five of them — one a near-flat ratio that indexes into a sawtooth
 * around 100 — is the difference between the reference's plot and a ball of
 * wool. Корзины against заказы is the funnel, and the picker is right there for
 * anything else.
 */
export const LONG_DEFAULT_METRICS = ['carts', 'orders']

/** Ink of the weekly uprights — lighter than the live chart's day separators. */
const GRID_UPRIGHT = '#E8E8E8'

/** Ink of the horizontal rules. */
const GRID_RULE = '#D9D9D9'

/** Date-axis ink and size: a scale, not a row of headings. */
const DATE_INK = '#8A8A8A'
const DATE_SIZE = 9
const DATE_ROTATE = 60

/** Opacity of the leading series' area fill. */
const AREA_OPACITY = 0.22

/** Room under the plot for a rotated date at {@link DATE_SIZE}. */
const PLOT_BOTTOM = 54

/**
 * Split a window into weeks, Monday-first.
 *
 * @param {string[]} days ISO days, oldest first.
 * @returns {Array<{from: number, to: number}>} Index ranges into `days`, `to`
 *   exclusive. The first and last weeks are partial whenever the window does
 *   not begin or end on a Monday, which is the ordinary case.
 */
export function weeksOf(days) {
  const weeks = []
  days.forEach((iso, index) => {
    // `Date.UTC` via the ISO string: a local-time parse shifts the day back an
    // hour east of Greenwich and puts every Monday in the previous week.
    const weekday = (new Date(`${iso}T00:00:00Z`).getUTCDay() + 6) % 7
    if (weekday === 0 || !weeks.length) weeks.push({ from: index, to: index })
    weeks[weeks.length - 1].to = index + 1
  })
  return weeks
}

/** The index of each week's first day — where an upright and a date belong. */
export function weekStarts(days) {
  return new Set(weeksOf(days).map((week) => week.from))
}

/**
 * Do all the picked metrics measure the same kind of thing?
 *
 * The live chart indexes everything to 100 because it has to: «Заказы, ₽» at
 * 500 000 beside «Затраты, ₽» at 7 000 share a unit, therefore an axis, and the
 * smaller of the two is a flat line along the bottom. That reasoning covers a
 * MIXED pick and nothing else. Корзины against заказы are both штуки — the
 * axis is already true for both, and indexing them buys nothing while costing
 * the thing the reference has and we did not: an axis whose numbers are the
 * numbers. It also stops the two series being drawn on different footings, an
 * index against a raw count, which is what put a line at exactly 100 on the
 * left edge of the plot and no way to tell it was not a measurement.
 *
 * @param {Array<{unit: string}>} specs The picked metrics.
 * @returns {boolean} True when one axis is honest for all of them as they are.
 */
function sharesOneUnit(specs) {
  return new Set(specs.map((spec) => spec.unit)).size <= 1
}

/** The largest finite number in a list, or `null`. */
function maxOf(values) {
  const finite = values.filter((value) => value != null && Number.isFinite(value))
  return finite.length ? Math.max(...finite) : null
}

/** How many rules the plot carries between the baseline and the top. */
const RULE_COUNT = 4

/**
 * A readable gap between two horizontal rules — 1, 2 or 5 times a power of ten.
 *
 * The scale stops at the data's own maximum (see the module docstring), so the
 * step cannot be derived by dividing a round ceiling: `283 / 4` is 70,75, and a
 * rule at 70,75 is a number nobody reads. Rounding the STEP instead puts the
 * rules on 0, 50, 100… and leaves the odd number where it belongs — at the top,
 * where it is the one fact the axis is reporting.
 *
 * @param {number} top The largest value plotted.
 * @returns {number} The gap between rules.
 */
export function ruleStep(top) {
  const rough = top / RULE_COUNT
  const power = 10 ** Math.floor(Math.log10(rough))
  const scaled = rough / power
  const nice = scaled <= 1 ? 1 : scaled <= 2 ? 2 : scaled <= 5 ? 5 : 10
  return nice * power
}

/**
 * One fitted chart: the whole window on the card's width, no ribbon.
 *
 * @param {object} view A display matrix (`matrixView` shape).
 * @param {{metrics?: string[], groups?: Array<object>, hover?: object}} [options]
 * @returns {object|null} `{legend, empty, option}`, or null for an empty window.
 */
export function buildFittedChart(view, { metrics = [], groups = [], hover } = {}) {
  if (!view?.days?.length) return null
  const days = view.days.map((day) => day.iso)
  const starts = weekStarts(days)

  const specs = metricSeriesSpecs(view, { metrics, groups })
  const rebase = !sharesOneUnit(specs)

  const series = specs.map((spec) => ({
    name: spec.name,
    // A column is drawn as a line like everything else — see the module
    // docstring for why nothing here is a column any more.
    type: 'line',
    unit: spec.unit,
    group: spec.group,
    color: spec.color,
    // Заказы are what the scale measures, so they are drawn as they are.
    ...(!rebase || spec.isRuler ? { data: spec.values } : indexed(spec.values)),
  }))

  // The reference tops its scale out at its own 67 rather than at a rounded
  // ceiling above it; a scale that stopped at 80 would spend a fifth of the
  // canvas on nothing.
  const top = maxOf(series.flatMap((entry) => entry.data))
  const ceiling = top ? Math.ceil(top) : undefined
  const option = buildChartOption({ days, axisMax: ceiling, hover, series })

  return {
    legend: series.map((entry) => ({ name: entry.name, color: entry.color })),
    empty: !series.length || series.every((entry) => entry.data.every((value) => value == null)),
    option: {
      ...option,
      // The axis is drawn in this same canvas rather than pinned beside it:
      // there is no ribbon to scroll away from, so there is nothing to pin.
      grid: { ...option.grid, left: AXIS_GUTTER_PX, right: 12, bottom: PLOT_BOTTOM },
      xAxis: {
        ...option.xAxis,
        // Lines only, so the first day sits ON the axis origin rather than
        // half a category in — which is what a filled area needs to close.
        boundaryGap: false,
        axisLabel: {
          ...option.xAxis.axisLabel,
          interval: (index) => starts.has(index),
          formatter: (_, index) => shortDayLabel(days[index]),
          color: DATE_INK,
          fontSize: DATE_SIZE,
          fontWeight: 'normal',
          rotate: DATE_ROTATE,
        },
        // The uprights are the week division. They stay whatever the labels
        // do: at a narrow card ECharts thins the dates, and the scale has to
        // survive that.
        splitLine: {
          show: true,
          interval: (index) => starts.has(index),
          lineStyle: { color: GRID_UPRIGHT, width: 1 },
        },
      },
      yAxis: {
        ...option.yAxis,
        ...(ceiling ? { interval: ruleStep(ceiling) } : {}),
        axisLabel: { ...option.yAxis.axisLabel, fontSize: 10 },
        splitLine: { lineStyle: { color: GRID_RULE, width: 1, type: [4, 4] } },
      },
      series: option.series.map((entry, index) => ({
        ...entry,
        symbolSize: 3.5,
        lineStyle: { ...entry.lineStyle, width: 1.6 },
        // Only the leading series is filled — see the module docstring.
        ...(index === 0 ? { areaStyle: { color: entry.color, opacity: AREA_OPACITY } } : {}),
      })),
    },
  }
}
