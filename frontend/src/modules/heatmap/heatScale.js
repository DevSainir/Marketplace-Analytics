/**
 * The heatmap's colour: where a cell sits between the NORM of the cells it is
 * compared with and their worst or best one, turned into a tint.
 *
 * Pure presentation — every figure is the backend's, and this only decides how
 * loudly to paint it.
 *
 * * **The norm is the median** of the compared cells — a typical day, which one
 *   outlier cannot drag. The middle between the minimum and the maximum is not
 *   a norm: one record day moves it for every other cell (owner, 2026-09-30).
 * * **Every cell off the norm is painted**, however slightly: a faint tint
 *   still says which side of usual the day fell on, where white says nothing.
 *   Only a cell exactly at the norm stays white.
 * * **Each side has its own scale.** Below the norm the tint grows to full at
 *   the worst cell, above it at the best — so a spike deepens only its own
 *   side and the ordinary days next to the norm stay pale.
 *
 * * **A hand-set norm replaces the median** («Норма: ручной ввод»), and the
 *   extremes stretch to include it: when every day sits under a norm of 80,
 *   the day furthest under it is the full red.
 *
 * Direction decides the hue: «больше — лучше» paints above the norm green,
 * «меньше — лучше» (DRR, CPC, CPM, CPO, the ad budget) paints it red. Prices,
 * SPP and stock have no better end: with the default norm they are painted in
 * the action hue by magnitude, the cheapest white; against a hand-set norm, in
 * the same hue by distance from it, either way.
 */

/** Strongest tint, as an alpha: the figure keeps the ordinary dark ink on it. */
const MAX_ALPHA = 0.5

/** Faintest tint of a cell off the norm — just enough to see which side it is on. */
const MIN_ALPHA = 0.05

/**
 * Min, median and max of the finite values in `values`; `null` when there are
 * none or they are all equal — with no spread there is no better or worse cell.
 *
 * @param {Iterable<number|null>} values
 * @returns {{min: number, median: number, max: number}|null}
 */
export function scaleOf(values) {
  const finite = []
  for (const value of values) {
    if (value !== null && value !== undefined && Number.isFinite(value)) finite.push(value)
  }
  if (!finite.length) return null
  finite.sort((a, b) => a - b)
  const min = finite[0]
  const max = finite[finite.length - 1]
  if (max <= min) return null
  const middle = Math.floor(finite.length / 2)
  const median = finite.length % 2 ? finite[middle] : (finite[middle - 1] + finite[middle]) / 2
  return { min, median, max }
}

/**
 * The scale around a hand-set `norm`: the norm in the median's place, the
 * extremes widened to include it. `null` when no value is finite.
 *
 * @param {Iterable<number|null>} values
 * @param {number} norm
 * @returns {{min: number, median: number, max: number, manual: true}|null}
 */
export function scaleAround(values, norm) {
  let min = norm
  let max = norm
  let any = false
  for (const value of values) {
    if (value === null || value === undefined || !Number.isFinite(value)) continue
    any = true
    if (value < min) min = value
    if (value > max) max = value
  }
  return any ? { min, median: norm, max, manual: true } : null
}

/**
 * How far a cell sits from the norm towards the extreme on its side: 0 at the
 * norm, ±1 at the minimum or maximum — signed, positive above the norm.
 *
 * @param {number|null} value
 * @param {{min: number, median: number, max: number}|null} scale
 * @returns {number|null} `null` when there is nothing to place.
 */
export function departure(value, scale) {
  if (value === null || value === undefined || !Number.isFinite(value) || !scale) return null
  const { min, median, max } = scale
  // `max > median` whenever a value is above it, and `min < median` below —
  // true of both scales, so neither division can be by zero.
  if (value > median) return Math.min(1, (value - median) / (max - median))
  if (value < median) return -Math.min(1, (median - value) / (median - min))
  return 0
}

/**
 * The style for a cell of a metric with no better end: action hue by
 * magnitude, the minimum white.
 *
 * @param {number|null} value
 * @param {{min: number, max: number}|null} scale
 * @returns {{background?: string}}
 */
function magnitudeStyle(value, scale) {
  if (value === null || value === undefined || !Number.isFinite(value) || !scale) return {}
  const share = Math.min(1, Math.max(0, (value - scale.min) / (scale.max - scale.min)))
  if (share === 0) return {}
  const alpha = MIN_ALPHA + (MAX_ALPHA - MIN_ALPHA) * share
  return { background: `rgb(var(--ui-action-rgb) / ${alpha.toFixed(3)})` }
}

/**
 * The style for a cell — its background; the figure keeps the ordinary ink.
 *
 * Built from the design tokens' channel triples, so the heatmap follows the
 * palette rather than carrying colours of its own.
 *
 * @param {number|null} value
 * @param {{min: number, median: number, max: number, manual?: true}|null} scale From
 *   {@link scaleOf} or {@link scaleAround}.
 * @param {'up'|'down'|'neutral'} direction
 * @returns {{background?: string}}
 */
export function heatStyle(value, scale, direction) {
  if (direction === 'neutral' && !scale?.manual) return magnitudeStyle(value, scale)
  const strength = departure(value, scale)
  if (strength === null || strength === 0) return {}
  const alpha = MIN_ALPHA + (MAX_ALPHA - MIN_ALPHA) * Math.abs(strength)
  if (direction === 'neutral')
    return { background: `rgb(var(--ui-action-rgb) / ${alpha.toFixed(3)})` }
  const better = direction === 'down' ? strength < 0 : strength > 0
  const channel = better ? '--ui-pos-rgb' : '--ui-neg-rgb'
  return { background: `rgb(var(${channel}) / ${alpha.toFixed(3)})` }
}
