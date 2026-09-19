/**
 * SANDBOX — two ways to make a quarter (or a year) fit the card.
 *
 * The live chart is laid out at a fixed width PER DAY and scrolled sideways.
 * That is right for a fortnight and wrong for a year: 365 days at 44px is nine
 * metres of ribbon, and the shape a reader came for — «когда это началось» —
 * is never on screen at once. Both layouts here drop the ribbon entirely: one
 * plot, the card's own width, every day of the window in it.
 *
 * What they do NOT drop is the day. Both keep a point per day, because the day
 * is the grain every other block of the page is read at and a weekly average is
 * a different number about a different thing. What changes is only how the
 * heavy marks are drawn:
 *
 * * `weekly-bars` — the COLUMNS fold into weeks (one column per week, its
 *   days summed), the lines stay daily. A column is a quantity, and 365 of
 *   them across a card is 1.5px each — a texture, not a bar. Fifty-two is a
 *   bar.
 * * `lines` — the columns BECOME lines, daily like the rest, and only the
 *   axis is weekly. Nothing is aggregated at all; the plot gets readable
 *   because a line at 1.5px a day is still a line.
 *
 * In both, the axis labels and the uprights land on week starts: at a year's
 * width a label per day is an inkblot.
 *
 * **Folding is per metric, and it is not always a sum.** Корзины and заказы
 * are flows — a week of them is their sum. Остатки are a LEVEL: a week of
 * stock is not seven times a day of it, so those average. Getting this wrong
 * draws a warehouse holding seven times what it holds.
 */
import {
  AXIS_GUTTER_PX,
  buildChartOption,
  niceCeiling,
  shortDayLabel,
} from '@/modules/labs/chartOptions'
import { indexed, metricSeriesSpecs } from '@/modules/labs/metricChart'

/** Catalogue keys whose value is a LEVEL rather than a flow — averaged, never summed. */
const LEVEL_METRICS = new Set(['stock_quantity', 'stock_total'])

/** Share of one week's width a whole row of columns may take. */
const WEEK_BAR_FILL = 600

/**
 * Split a window into weeks, Monday-first.
 *
 * @param {string[]} days ISO days, oldest first.
 * @returns {Array<{from: number, to: number, mid: number}>} Index ranges into
 *   `days`, `to` exclusive. The first and last weeks are partial whenever the
 *   window does not begin or end on a Monday, which is the ordinary case.
 */
export function weeksOf(days) {
  const weeks = []
  days.forEach((iso, index) => {
    // `Date.UTC` via the ISO string: a local-time parse shifts the day back an
    // hour east of Greenwich and puts every Monday in the previous week.
    const weekday = (new Date(`${iso}T00:00:00Z`).getUTCDay() + 6) % 7
    if (weekday === 0 || !weeks.length) weeks.push({ from: index, to: index, mid: index })
    const week = weeks[weeks.length - 1]
    week.to = index + 1
    week.mid = week.from + Math.floor((week.to - week.from - 1) / 2)
  })
  return weeks
}

/** The index of each week's first day — where a label and an upright belong. */
function weekStartIndexes(weeks) {
  return new Set(weeks.map((week) => week.from))
}

/**
 * Fold a daily series into one value per week, placed at the week's mid-day.
 *
 * The result is still a day-long array — every layout here draws on ONE daily
 * axis, so a weekly column is a value at the week's middle index and nulls
 * either side of it. That keeps the lines and the columns on the same ruler
 * without a second axis to keep in step with the first.
 *
 * @param {Array<number|null>} values One value per day.
 * @param {Array<{from: number, to: number, mid: number}>} weeks
 * @param {'sum'|'avg'} how Flows sum; levels average.
 * @returns {Array<number|null>} Nulls except at each week's mid index.
 */
export function foldWeekly(values, weeks, how) {
  const folded = values.map(() => null)
  for (const week of weeks) {
    const inside = values.slice(week.from, week.to).filter((value) => value != null)
    // A week WB reported nothing for stays null: a zero would draw a column
    // saying the card sold nothing, where the truth is that nobody looked.
    if (!inside.length) continue
    const total = inside.reduce((sum, value) => sum + value, 0)
    folded[week.mid] = how === 'avg' ? total / inside.length : total
  }
  return folded
}

/** The largest finite number in a list, or `null`. */
function maxOf(values) {
  const finite = values.filter((value) => value != null && Number.isFinite(value))
  return finite.length ? Math.max(...finite) : null
}

/**
 * Where the ruler tops out, read off what is actually drawn.
 *
 * The live chart anchors its scale to заказов per day whether or not заказы are
 * ticked. Here the same series may be daily or weekly depending on the layout,
 * so the anchor is the PLOTTED orders — a scale of заказов either way, just of
 * the week's in one of the two.
 */
function ceilingOf(series) {
  const ruler = series.find((entry) => entry.isRuler)
  const anchor = ruler ? niceCeiling(maxOf(ruler.data)) : niceCeiling(null)
  const plotted = maxOf(series.flatMap((entry) => entry.data))
  return Math.max(anchor, plotted == null ? 0 : niceCeiling(plotted))
}

/**
 * One fitted chart: the whole window on the card's width, no ribbon.
 *
 * @param {object} view A display matrix (`matrixView` shape).
 * @param {{metrics?: string[], groups?: Array<object>, hover?: object,
 *   mode?: 'weekly-bars'|'lines'}} options `mode` is the experiment — see the
 *   module docstring.
 * @returns {object|null} `{legend, empty, option, weeks}`, or null for an
 *   empty window.
 */
export function buildFittedChart(view, { metrics = [], groups = [], hover, mode } = {}) {
  if (!view?.days?.length) return null
  const days = view.days.map((day) => day.iso)
  const weeks = weeksOf(days)
  const starts = weekStartIndexes(weeks)
  const weekly = mode === 'weekly-bars'

  const series = metricSeriesSpecs(view, { metrics, groups }).map((spec) => {
    // In `lines` mode a column is simply drawn as a line; nothing is folded.
    const asBar = weekly && spec.type === 'bar'
    const values = asBar
      ? foldWeekly(spec.values, weeks, LEVEL_METRICS.has(spec.key) ? 'avg' : 'sum')
      : spec.values
    return {
      name: spec.name,
      type: asBar ? 'bar' : 'line',
      unit: spec.unit,
      group: spec.group,
      color: spec.color,
      isRuler: spec.isRuler,
      // Заказы are what the scale measures, so they are drawn as they are —
      // and an index is rebased on the series actually plotted, which for a
      // folded one is its first WEEK rather than its first day.
      ...(spec.isRuler ? { data: values } : indexed(values)),
    }
  })

  const option = buildChartOption({ days, axisMax: ceilingOf(series), hover, series })
  const bars = series.filter((entry) => entry.type === 'bar').length

  return {
    weeks: weeks.length,
    legend: series.map((entry) => ({ name: entry.name, color: entry.color })),
    empty: !series.length || series.every((entry) => entry.data.every((value) => value == null)),
    option: {
      ...option,
      // The axis is drawn in this same canvas rather than pinned beside it:
      // there is no ribbon to scroll away from, so there is nothing to pin.
      grid: { ...option.grid, left: AXIS_GUTTER_PX, right: 12 },
      xAxis: {
        ...option.xAxis,
        axisLabel: {
          ...option.xAxis.axisLabel,
          // A label per day is an inkblot at this width; one per week starts
          // is the same date scale, printed where the eye can use it.
          interval: (index) => starts.has(index),
          formatter: (_, index) => shortDayLabel(days[index]),
          fontSize: 11,
        },
        splitLine: { ...option.xAxis.splitLine, interval: (index) => starts.has(index) },
      },
      series: option.series.map((entry) =>
        entry.type === 'bar'
          ? {
              // Percent of ONE day's width: a week's column has to be about
              // seven of those, and a percentage rescales itself when the card
              // does — which is the whole point of dropping the fixed ribbon.
              ...entry,
              barWidth: `${Math.floor(WEEK_BAR_FILL / Math.max(bars, 1))}%`,
              barMaxWidth: undefined,
              barGap: '10%',
            }
          : entry,
      ),
    },
  }
}
