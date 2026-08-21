/**
 * The shared look of every monitoring chart: palette, axes, grid, tooltip.
 *
 * Split from `chartSpecs.js` so the WHAT (which metric goes on which chart)
 * and the HOW (what a chart looks like) stay separately readable — the specs
 * file is a data table, this one is the theme.
 *
 * Ink and surface mirror `tailwind.config.js` (text-muted, border-subtle,
 * bg-surface). They are repeated as hex because ECharts paints onto a canvas
 * and cannot resolve a Tailwind class; when a token moves, it moves here too.
 */
import { formatCurrency, formatNumber, formatPercent } from '@/core/utils/format'

/** Tailwind `textColor.muted` / `border.subtle` / `backgroundColor.surface`. */
const INK_MUTED = '#858585'
const INK_PRIMARY = '#101010'
const LINE_SUBTLE = '#E0E0E0'
const SURFACE = '#F1F1F1'

/**
 * The categorical series palette, in FIXED slot order — slot 1 is always the
 * first series of a chart, never recycled by rank.
 *
 * These eight hues are the validated default of the `dataviz` skill, re-checked
 * against THIS app's chart surface (#F1F1F1): lightness band, chroma floor,
 * adjacent-pair CVD separation (worst ΔE 9.1) and normal-vision separation
 * (worst ΔE 19.6) all pass. The app's own semantic tokens are deliberately not
 * used here — `status.*` is reserved for state (good/bad), and reusing it for
 * «series 4» would make a colour mean two things on one screen.
 *
 * Four of the eight sit under 3:1 contrast on this surface, which obliges
 * relief: every chart carries a legend and a hover tooltip with the exact
 * numbers, and the full data table («Метрики по дням») sits directly above.
 * A ninth series is not a generated hue — fold it into a bucket or split the
 * chart.
 */
export const SERIES_COLORS = [
  '#2a78d6', // blue
  '#eb6834', // orange
  '#1baf7a', // aqua
  '#eda100', // yellow
  '#e87ba4', // magenta
  '#008300', // green
  '#4a3aa7', // violet
  '#e34948', // red
]

/** Value formatters by the unit a chart's single axis measures. */
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

/** Axis ticks carry no unit — the chart title states it once. */
function axisLabel(unit, value) {
  return unit === 'percent' ? `${formatNumber(value)}%` : formatNumber(value)
}

/** "2026-07-05" -> "05.07" — the full year would not fit 30 columns. */
export function shortDayLabel(iso) {
  const [, month, day] = iso.split('-')
  return `${day}.${month}`
}

/** One series' mark spec: 2px lines, rounded bar ends, a surface gap in stacks. */
function seriesMark(series, color, stack) {
  const shared = { name: series.name, data: series.data, color, z: 3 }
  if (series.type === 'bar') {
    return {
      ...shared,
      type: 'bar',
      stack,
      // Rounding only the top of a STACK would need the topmost non-null
      // segment per day, which is a calculation over the data; a stack gets
      // the surface gap instead and square ends.
      itemStyle: stack ? { borderColor: SURFACE, borderWidth: 1 } : { borderRadius: [4, 4, 0, 0] },
      barMaxWidth: 28,
    }
  }
  return {
    ...shared,
    type: 'line',
    stack,
    smooth: false,
    // A 30-day window puts a dot every ~30px; the crosshair tooltip reads the
    // values instead, and the symbol grows to 8px on hover.
    showSymbol: false,
    symbol: 'circle',
    symbolSize: 8,
    lineStyle: { width: 2 },
    areaStyle: series.area ? { opacity: 0.18 } : undefined,
    // A gap in the data is a day WB served nothing — joining across it would
    // draw a trend that never happened.
    connectNulls: false,
  }
}

/**
 * Headroom above the tallest mark, as a fraction of the axis range.
 *
 * Without it ECharts fits the axis to the data and the peak day touches the
 * top edge of the plot — «Цена» and «Остатки» both ran flush against it, where
 * a line reads as clipped rather than as a maximum, and a tooltip opening near
 * the peak has nowhere to go.
 */
const AXIS_HEADROOM = '12%'

/** The value-axis spec shared by both layouts (single plot and panels). */
function valueAxis(unit, { scale }) {
  return {
    type: 'value',
    scale,
    // `boundaryGap`, not a computed `max`: padding the extent by hand pins the
    // axis to an arbitrary number and ECharts prints it as the top tick
    // («481 900,432»). This pads the same way but leaves the tick algorithm to
    // pick round numbers.
    //
    // The TOP only. Padding the bottom too sent «ДРР» — which never goes below
    // zero — down to a −2% gridline, and an axis that shows an impossible value
    // is worse than a line sitting near the floor. On a scaled axis ECharts
    // still rounds the minimum down to a tick of its own accord.
    boundaryGap: [0, AXIS_HEADROOM],
    min: scale ? undefined : 0,
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: { color: INK_MUTED, fontSize: 11, formatter: (v) => axisLabel(unit, v) },
    splitLine: { lineStyle: { color: LINE_SUBTLE, type: 'dashed' } },
  }
}

/** One tooltip block for a linked small-multiples hover: date, then a row each. */
function panelsTooltip(unit) {
  return (params) => {
    const points = [...params].sort((a, b) => a.seriesIndex - b.seriesIndex)
    const rows = points
      .map(
        (point) =>
          `<div style="display:flex;gap:24px;justify-content:space-between">` +
          `<span>${point.marker}${point.seriesName}</span>` +
          `<b>${formatValue(unit, point.value)}</b></div>`,
      )
      .join('')
    return `<div style="color:${INK_MUTED};margin-bottom:4px">${points[0].axisValue}</div>${rows}`
  }
}

/**
 * A complete ECharts option for a SMALL-MULTIPLES chart: one thin panel per
 * series, stacked, all sharing the day axis.
 *
 * The remedy for series that share a unit but not an order of magnitude — the
 * funnel's клики (thousands), корзины (hundreds) and заказы (tens). On one
 * scale the last two lie flat on the axis; a second y-axis would be worse
 * still. Each panel gets its own scale and its own title, so identity comes
 * from position and words rather than from colour alone, and one crosshair
 * runs through all three (`axisPointer.link`) so a day reads across the funnel
 * at a glance.
 *
 * @param {{days: string[], unit: string, series: Array<{name: string,
 *   type: string, data: Array<number|null>}>}} spec
 */
function buildPanelsOption({ days, unit, series }) {
  const count = series.length
  // Percentages of the canvas: a title strip above each panel, the day labels
  // under the last one only.
  const TOP = 9
  const BOTTOM = 10
  const GAP = 10
  const height = (100 - TOP - BOTTOM - GAP * (count - 1)) / count
  const panelTop = (index) => TOP + index * (height + GAP)

  return {
    animationDuration: 300,
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#FFFFFF',
      borderColor: LINE_SUBTLE,
      borderWidth: 1,
      padding: [8, 12],
      textStyle: { color: INK_PRIMARY, fontSize: 12 },
      // One block for the whole funnel. Left to itself, a linked axis pointer
      // emits one section PER panel — the same date printed three times, and
      // the panels listed bottom-up.
      formatter: panelsTooltip(unit),
    },
    axisPointer: { link: [{ xAxisIndex: 'all' }], lineStyle: { color: INK_MUTED } },
    grid: series.map((_, index) => ({
      left: 4,
      right: 8,
      top: `${panelTop(index)}%`,
      height: `${height}%`,
      containLabel: true,
    })),
    xAxis: series.map((_, index) => ({
      type: 'category',
      gridIndex: index,
      data: days.map(shortDayLabel),
      boundaryGap: false,
      axisLine: { lineStyle: { color: LINE_SUBTLE } },
      axisTick: { show: false },
      // Only the bottom panel carries the dates; repeating them three times
      // would cost a third of the plot to say the same thing twice.
      axisLabel: { show: index === count - 1, color: INK_MUTED, fontSize: 11 },
    })),
    yAxis: series.map((entry, index) => ({
      ...valueAxis(unit, { scale: true }),
      gridIndex: index,
      // The panel's own caption. It rides on the axis rather than on a `title`
      // component so it stays glued to the panel when the grid is laid out in
      // percentages.
      name: entry.name,
      nameLocation: 'end',
      nameGap: 10,
      nameTextStyle: { color: INK_MUTED, fontSize: 11, align: 'left' },
      splitNumber: 2,
    })),
    series: series.map((entry, index) => ({
      ...seriesMark(entry, SERIES_COLORS[entry.colorIndex ?? index], null),
      xAxisIndex: index,
      yAxisIndex: index,
    })),
  }
}

/**
 * A complete ECharts option for one chart.
 *
 * Deliberately single-axis: two y-scales on one plot make any crossing look
 * like a relationship, so a second unit gets its own chart instead.
 *
 * @param {{days: string[], unit: string, stack: string|null,
 *   series: Array<{name: string, type: string, data: Array<number|null>,
 *   area?: boolean}>}} spec
 */
export function buildChartOption({ days, unit, stack = null, panels = false, series }) {
  if (panels) return buildPanelsOption({ days, unit, series })

  const hasBar = series.some((entry) => entry.type === 'bar')

  return {
    animationDuration: 300,
    // A fixed one-row allowance under the plot. The legend is pinned to one
    // row (below), so this can be a constant — a wrapping legend would grow
    // into the grid on a narrow screen, and ECharts does not reflow the grid
    // for it.
    grid: { left: 4, right: 8, top: 12, bottom: 30, containLabel: true },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: hasBar ? 'shadow' : 'line' },
      backgroundColor: '#FFFFFF',
      borderColor: LINE_SUBTLE,
      borderWidth: 1,
      padding: [8, 12],
      textStyle: { color: INK_PRIMARY, fontSize: 12 },
      valueFormatter: (value) => formatValue(unit, value),
    },
    legend: {
      bottom: 0,
      // The composition charts carry eight entries: at desktop width they all
      // fit one row, and on a phone `scroll` pages through them instead of
      // wrapping over the plot.
      type: series.length > 4 ? 'scroll' : 'plain',
      pageIconSize: 9,
      pageTextStyle: { color: INK_MUTED, fontSize: 11 },
      icon: 'roundRect',
      itemWidth: 10,
      itemHeight: 10,
      itemGap: 14,
      textStyle: { color: INK_MUTED, fontSize: 11 },
    },
    xAxis: {
      type: 'category',
      data: days.map(shortDayLabel),
      boundaryGap: hasBar,
      axisLine: { lineStyle: { color: LINE_SUBTLE } },
      axisTick: { show: false },
      axisLabel: { color: INK_MUTED, fontSize: 11 },
    },
    // Bars encode magnitude by length and a composition sums from nothing, so
    // both are anchored to zero. A plain line chart is not: pinning цена
    // 990–1290 ₽ to a zero baseline spends four fifths of the plot on empty
    // space and flattens the very change the chart exists to show.
    yAxis: valueAxis(unit, { scale: !hasBar && !stack }),
    // `colorIndex` pins a slot to the ENTITY (a traffic bucket keeps its hue on
    // every slide it appears on); without one, a series takes the slot its
    // position implies. Slots are never recycled — see SERIES_COLORS.
    series: series.map((s, index) => seriesMark(s, SERIES_COLORS[s.colorIndex ?? index], stack)),
  }
}
