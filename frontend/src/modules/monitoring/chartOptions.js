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
    // Every day gets a dot. The plot is laid out at a fixed width PER DAY and
    // scrolled (see `DAY_WIDTH`), so there is always room for them — and on a
    // near-flat series they are what makes one day legibly different from the
    // next, rather than a line that looks straight.
    showSymbol: true,
    symbol: 'circle',
    symbolSize: 5,
    emphasis: { scale: 1.8 },
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

/**
 * Plot geometry, in pixels and shared by both copies of a chart (see
 * `axisOnlyOption`). `PLOT_BOTTOM` is the strip the day labels sit in.
 */
const PLOT_TOP = 12
const PLOT_BOTTOM = 28

/** Width of the pinned y-axis column, wide enough for «500 000» and «Корзины». */
export const AXIS_GUTTER_PX = 74

/**
 * The value-axis spec shared by both layouts (single plot and panels).
 *
 * A note on `splitNumber`, which is deliberately NOT set: ECharts picks the
 * tick interval from it and then snaps the axis minimum DOWN to a multiple of
 * that interval. Asking for two ticks on a «Корзины» panel spanning 90-215
 * bought an interval of 100 and therefore a minimum of 0 — `scale: true`
 * honoured to the letter and useless in practice, with the whole series
 * crushed into the top third and 97 and 118 a hair apart. Left alone, ECharts
 * chooses ~5 ticks, an interval of 30, and a minimum of 90.
 */
function valueAxis(unit, { scale }) {
  return {
    type: 'value',
    scale,
    // Head-room above the tallest mark, and the two ways of getting it — which
    // are mutually exclusive, so each axis takes the one that fits it.
    //
    // A ZERO-ANCHORED axis (bars, stacks) uses `boundaryGap`. Not a computed
    // `max`: padding the extent by hand pins the axis to an arbitrary number
    // and ECharts prints it as the top tick («481 900,432»), where this pads
    // the same way and still lets the tick algorithm pick round numbers. Only
    // the top is padded — padding the bottom sent «ДРР», which never goes
    // negative, down to a −2% gridline.
    //
    // A SCALED axis gets NONE, because any `boundaryGap` on a value axis makes
    // ECharts include zero again, whatever `scale` says — measured both as
    // `[0, …]` and `['0%', …]`. That is exactly what flattened the funnel: with
    // one spike day at 215 the «Корзины» panel ran 0-250 and the 97-118 band
    // the series actually lives in was a few pixels tall. Without it the panel
    // fits 30-210, and `scale`'s own rounding-up to the next whole tick leaves
    // the head-room anyway (verified on «Цены»: a 4 370 ₽ peak under a 4 400 ₽
    // top tick).
    boundaryGap: scale ? undefined : ['0%', AXIS_HEADROOM],
    min: scale ? undefined : 0,
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: {
      color: INK_MUTED,
      fontSize: 11,
      // A funnel panel is ~90px tall and ECharts sizes its tick count for a
      // full plot, so «100» and «120» collided into a smudge. Dropping a
      // colliding label is the right lever — forcing a smaller `splitNumber`
      // coarsens the interval, and a coarse interval is what snaps the axis
      // minimum back down to zero.
      hideOverlap: true,
      formatter: (v) => axisLabel(unit, v),
    },
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
 * The same chart with its y axis muted — the copy that scrolls.
 *
 * Its labels and panel captions belong to the pinned copy standing to its left;
 * drawn here too they would scroll away mid-ribbon and collide with the data on
 * the way out.
 *
 * @param {object} option A built chart option (either layout).
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
 * the same series and the same `scale`, give them the same height and the same
 * grid top/bottom, and ECharts independently arrives at the same ticks in the
 * same places. The series are kept (invisible) for exactly that reason —
 * dropping them would drop the extent with them.
 *
 * @param {object} option A built chart option (either layout).
 * @returns {object} The same option, stripped to the axis.
 */
export function axisOnlyOption(option, gutter = AXIS_GUTTER_PX) {
  // Both layouts pass through here — one plot or three — so each field keeps
  // whatever shape it arrived in. ECharts accepts either, but returning an
  // array where the scrolling copy has a bare object makes the two impossible
  // to compare, in a test or by eye.
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
    })),
    yAxis: mapAxis(option.yAxis, (axis) => ({ ...axis, splitLine: { show: false } })),
    // Present in the data, absent on screen: they set the extent and draw
    // nothing. `silent` keeps them from answering a hover that is not theirs.
    series: option.series.map((entry) => ({
      ...entry,
      silent: true,
      showSymbol: false,
      lineStyle: { ...entry.lineStyle, opacity: 0 },
      areaStyle: entry.areaStyle ? { ...entry.areaStyle, opacity: 0 } : undefined,
      itemStyle: { ...entry.itemStyle, opacity: 0, borderWidth: 0 },
    })),
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
  // and the scroll handle under the last one only. The chart is given extra
  // HEIGHT to spend here (see `PANEL_CHART_HEIGHT`) — three panels sharing a
  // single-plot's 340px leaves each about 50px, which is not a trend line, it
  // is a horizon.
  const TOP = 8
  const BOTTOM = 11
  const GAP = 9
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
      left: 0,
      right: 8,
      top: `${panelTop(index)}%`,
      height: `${height}%`,
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
      axisLabel: {
        show: index === count - 1,
        color: INK_MUTED,
        fontSize: 11,
        hideOverlap: true,
      },
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
      // Aligned RIGHT, which reads backwards but is what keeps it on screen:
      // the caption is anchored to the axis line, and the axis line is at the
      // right-hand edge of the pinned gutter. Aligned left it grows into the
      // scroller and is clipped to «К».
      nameTextStyle: { color: INK_MUTED, fontSize: 11, align: 'right' },
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
    // A fixed allowance under the plot: one legend row (it is pinned to one
    // row below, since a wrapping legend would grow into the grid and ECharts
    // does not reflow it) plus the scroll handle.
    // Explicit pixels, NOT `containLabel`: this plot is rendered twice — once
    // wide inside the scroller and once as a narrow pinned axis beside it — and
    // `containLabel` sizes the grid around whichever labels each copy happens
    // to show, which would slide the two apart vertically by a few pixels and
    // leave every gridline off by that much.
    grid: { left: 0, right: 8, top: PLOT_TOP, bottom: PLOT_BOTTOM },
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
    xAxis: {
      type: 'category',
      data: days.map(shortDayLabel),
      boundaryGap: hasBar,
      axisLine: { lineStyle: { color: LINE_SUBTLE } },
      axisTick: { show: false },
      axisLabel: { color: INK_MUTED, fontSize: 11, hideOverlap: true },
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
