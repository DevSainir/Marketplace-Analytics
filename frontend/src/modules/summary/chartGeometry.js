/**
 * Pure geometry for the summary's line charts.
 *
 * Kept out of the component so the axis rounding and the point mapping can be
 * read — and tested — without a DOM. The shapes are the ones the original
 * one-pager drew; what changed is that they are computed in real pixels rather
 * than in a scaled viewBox.
 */

/**
 * Plot margins, in px. Left is wide enough for a «1,2 млн» tick; right for a
 * «20 %» one, because the ДРР charts carry a second axis over there.
 */
export const MARGIN = { left: 58, right: 44, top: 12, bottom: 26 }

/** Roughly how many gaps between grid lines to aim for. */
const TICKS = 4

/**
 * Round a magnitude up to something a person would choose.
 *
 * 1, 2, 2.5, 5 or 10 times a power of ten — so the ticks land on readable
 * numbers instead of on the data's own maximum.
 *
 * @param {number} value
 * @returns {number}
 */
export function niceMax(value) {
  if (!(value > 0)) return 1
  const power = 10 ** Math.floor(Math.log10(value))
  const rest = value / power
  const step = rest <= 1 ? 1 : rest <= 2 ? 2 : rest <= 2.5 ? 2.5 : rest <= 5 ? 5 : 10
  return step * power
}

/**
 * Short money for an axis tick: 1 234 567 -> «1,2 млн».
 *
 * An axis carrying full figures is unreadable at this width, and the tooltip
 * is where the exact number belongs.
 *
 * @param {number} value
 * @returns {string}
 */
export function shortNumber(value) {
  if (!Number.isFinite(value)) return '—'
  const size = Math.abs(value)
  if (size >= 1e6)
    return `${(value / 1e6).toLocaleString('ru-RU', { maximumFractionDigits: 1 })} млн`
  if (size >= 1e4) return `${Math.round(value / 1e3).toLocaleString('ru-RU')} тыс`
  return Math.round(value).toLocaleString('ru-RU')
}

/**
 * Everything a line chart needs to draw itself.
 *
 * @param {object} options
 * @param {number} options.width Measured container width, px.
 * @param {number} options.height Chart height, px.
 * @param {Array<{values: Array<number|null>}>} options.series
 * @param {number} options.count How many points on the x axis.
 * @returns {object} Scales, grid ticks and the plot rectangle.
 */
export function buildScales({ width, height, series, count }) {
  const innerWidth = Math.max(1, width - MARGIN.left - MARGIN.right)
  const innerHeight = Math.max(1, height - MARGIN.top - MARGIN.bottom)

  const x = (index) =>
    MARGIN.left + (count < 2 ? innerWidth / 2 : (index / (count - 1)) * innerWidth)

  // Two independent vertical scales. A ДРР line lives between 0 and 20 while
  // the orders beside it are in the thousands: on one axis the percentage is a
  // flat line on the floor, which is the one shape it must never have.
  const left = buildAxis(
    series.filter((line) => line.axis !== 'right'),
    innerHeight,
  )
  const right = buildAxis(
    series.filter((line) => line.axis === 'right'),
    innerHeight,
  )
  const hasRight = series.some((line) => line.axis === 'right')

  return {
    x,
    y: left.y,
    rightY: right.y,
    ticks: left.ticks,
    rightTicks: hasRight ? right.ticks : [],
    min: left.min,
    max: left.max,
    innerWidth,
    innerHeight,
    plotRight: MARGIN.left + innerWidth,
    plotBottom: MARGIN.top + innerHeight,
    hasNegative: left.min < 0,
    zeroY: left.y(0),
  }
}

/**
 * One vertical scale: its rounded ends, its grid values and its mapping.
 *
 * @param {Array<{values: Array<number|null>, percent?: boolean}>} series
 * @param {number} innerHeight Plot height, px.
 * @returns {{y: (value: number) => number, ticks: object[], min: number, max: number}}
 */
function buildAxis(series, innerHeight) {
  let high = 0
  let low = 0
  for (const line of series) {
    for (const value of line.values) {
      if (!Number.isFinite(value)) continue
      if (value > high) high = value
      if (value < low) low = value
    }
  }
  // The axis is built from a STEP, not from its two ends. Rounding the ends
  // independently puts zero between two grid lines whenever a series goes
  // negative — and a margin chart is read against exactly that line. A step
  // that divides both ends makes zero a tick by construction.
  const step = niceMax((Math.max(high, 0) - Math.min(low, 0)) / TICKS) || 1
  const min = Math.floor(Math.min(low, 0) / step) * step
  const max = Math.ceil(Math.max(high, 0) / step) * step || step
  const span = max - min || 1
  const percent = series.some((line) => line.percent)

  const y = (value) => MARGIN.top + innerHeight - ((value - min) / span) * innerHeight

  const ticks = []
  for (let value = min; value <= max + step / 2; value += step) {
    // Re-snapped to the step: repeated addition of a fractional step drifts,
    // and a tick labelled «-0» is the visible end of that drift.
    const snapped = Math.round(value / step) * step
    ticks.push({
      value: snapped,
      label: percent ? `${shortNumber(snapped)} %` : shortNumber(snapped),
      y: y(snapped),
    })
  }

  return { y, ticks, min, max }
}

/**
 * An SVG path through a series, breaking wherever a point is missing.
 *
 * A gap in coverage must read as a gap: joining across it would draw a straight
 * line through days nobody measured and make the harvest look complete.
 *
 * @param {Array<number|null>} values
 * @param {(index: number) => number} x
 * @param {(value: number) => number} y
 * @returns {string}
 */
export function linePath(values, x, y) {
  let path = ''
  let pen = 'M'
  values.forEach((value, index) => {
    if (!Number.isFinite(value)) {
      pen = 'M'
      return
    }
    path += `${pen}${x(index).toFixed(1)} ${y(value).toFixed(1)} `
    pen = 'L'
  })
  return path.trim()
}

/**
 * Which x-axis labels to print, so they never collide.
 *
 * @param {number} count Points on the axis.
 * @param {number} innerWidth Plot width, px.
 * @returns {number} Print every n-th label.
 */
export function labelStep(count, innerWidth) {
  const fits = Math.max(2, Math.floor(innerWidth / 58))
  return Math.max(1, Math.ceil(count / fits))
}
