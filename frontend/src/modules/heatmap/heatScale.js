/**
 * The heatmap's colour: how far a cell sits from what is NORMAL for the cells
 * it is compared with, turned into a tint.
 *
 * Pure presentation — every figure is the backend's, and this only decides how
 * loudly to paint it.
 *
 * * **The norm is the median** of the compared cells — a typical day, which one
 *   outlier cannot drag the way it drags a min or a mean.
 * * **Near the norm is not painted.** Within the metric's band of it (±20 %
 *   by default, ±5 % for prices) the cell stays white; for counts (заказы,
 *   корзины, переходы) the band is at least ±√norm too, because 3 orders
 *   against a norm of 5 is ordinary noise for a small card.
 * * **Distance is a RATIO, not a difference.** Half the norm and twice the
 *   norm are equally far from it. Measured as a percentage, a fall can never
 *   pass −100 % while a rise has no ceiling, so 30 orders against a norm of 77
 *   (−61 %) read as a pale «slightly less» and a table whose norm is a couple
 *   of orders had no room to show anything red at all (2026-09-29).
 * * **Beyond the band the tint grows along a soft curve**: 1.5x the norm is a
 *   light-to-medium tint, 2x a strong one, 2.5x (or 0.4x) near full.
 *
 * Direction decides the hue: «больше — лучше» paints above the norm green,
 * «меньше — лучше» (ДРР, CPC, CPM, CPO, the ad budget) paints it red. Prices,
 * СПП and stock have no better end and are painted in the action hue by
 * distance from the norm alone.
 */

/** Default share of the norm that still counts as «обычный день». */
export const NORMAL_BAND = 0.2

/** How fast the tint saturates past the band, in log units: bigger = gentler. */
const SOFTNESS = 0.5

/** Tint of the faintest painted cell and of the strongest, as alphas. */
const MIN_ALPHA = 0.12
const MAX_ALPHA = 0.8

/** From this alpha on a dark hue the figure is printed white to stay legible. */
const INK_FLIP_ALPHA = 0.5

/**
 * The norm of the compared cells: their median. `null` when fewer than three
 * cells carry a value — two points have no «usual».
 *
 * @param {Iterable<number|null>} values
 * @returns {{median: number}|null}
 */
export function normOf(values) {
  const finite = []
  for (const value of values) {
    if (value !== null && value !== undefined && Number.isFinite(value)) finite.push(value)
  }
  if (finite.length < 3) return null
  finite.sort((a, b) => a - b)
  const middle = Math.floor(finite.length / 2)
  const median = finite.length % 2 ? finite[middle] : (finite[middle - 1] + finite[middle]) / 2
  return { median }
}

/**
 * How strongly a cell departs from the norm: 0 inside the normal band, rising
 * softly towards 1, signed — positive above the norm, negative below.
 *
 * @param {number|null} value
 * @param {{median: number}|null} norm
 * @param {{count?: boolean, band?: number}} [options] `count` widens the band to
 *   ±√norm; `band` is the metric's own normal band as a share of the norm.
 * @returns {number|null} `null` when there is nothing to place.
 */
export function departure(value, norm, { count = false, band = NORMAL_BAND } = {}) {
  if (value === null || value === undefined || !Number.isFinite(value) || !norm) return null
  const { median } = norm
  if (count && Math.abs(value - median) <= Math.sqrt(Math.max(median, 1))) return 0
  if (median <= 0 || value < 0) {
    // No ratio exists against a zero or negative norm (a card that usually
    // sells nothing, a refund-heavy profit): anything clearly away from it is
    // a full departure, and the sign says which way.
    return Math.abs(value - median) < 1e-9 ? 0 : Math.sign(value - median)
  }
  if (value === 0) return -1
  const distance = Math.log(value / median)
  const beyond = Math.abs(distance) - Math.log(1 + band)
  if (beyond <= 0) return 0
  return Math.sign(distance) * Math.tanh(beyond / SOFTNESS)
}

/**
 * The style for a cell — background and, on a strong dark tint, white ink.
 *
 * Built from the design tokens' channel triples, so the heatmap follows the
 * palette rather than carrying colours of its own.
 *
 * @param {number|null} strength From {@link departure}.
 * @param {'up'|'down'|'neutral'} direction
 * @returns {{background?: string, color?: string}}
 */
export function heatStyle(strength, direction) {
  if (strength === null || strength === 0) return {}
  const alpha = MIN_ALPHA + (MAX_ALPHA - MIN_ALPHA) * Math.abs(strength)
  let channel = '--ui-action-rgb'
  if (direction !== 'neutral') {
    const better = direction === 'down' ? strength < 0 : strength > 0
    channel = better ? '--ui-pos-rgb' : '--ui-neg-rgb'
  }
  const style = { background: `rgb(var(${channel}) / ${alpha.toFixed(3)})` }
  if (alpha >= INK_FLIP_ALPHA) style.color = '#fff'
  return style
}
