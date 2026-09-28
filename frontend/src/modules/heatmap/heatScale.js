/**
 * The heatmap's colour: how far a cell sits from what is NORMAL for the cells
 * it is compared with, turned into a tint.
 *
 * Pure presentation — every figure is the backend's, and this only decides how
 * loudly to paint it.
 *
 * It used to place a cell between the worst and the best of its range. That
 * always has a best and a worst day, however flat the week was, so a row of
 * 14-15-16 flickered red and green and nothing ever read as «обычный день».
 * Now:
 *
 * * **The norm is the median** of the compared cells — a typical day, which one
 *   outlier cannot drag the way it drags a min or a mean.
 * * **Near the norm is not painted.** Within ±20 % of it the cell stays white;
 *   for counts (заказы, корзины, переходы) the band is at least ±√norm too,
 *   because 3 orders against a norm of 5 is ordinary noise for a small card.
 * * **Beyond it the tint grows softly** (a tanh curve): a day +50 % over the
 *   norm is a light tint, +100 % a medium one, and only about +200 % is full.
 *   Measured on «Демо», 30 days (2026-09-28): 1–8 % of cells reach the
 *   strong end depending on the metric, 42–88 % stay white.
 *
 * Direction still decides the hue: «больше — лучше» paints above the norm
 * green, «меньше — лучше» (ДРР, CPC, CPM, CPO, the ad budget) paints it red.
 * Prices, СПП and stock have no better end and are painted in the action hue by
 * distance from the norm alone.
 */

/** Share of the norm that still counts as «обычный день». */
export const NORMAL_BAND = 0.2

/** How fast the tint saturates past the band: bigger = gentler. */
const SOFTNESS = 0.8

/** Tint of the faintest painted cell and of the strongest, as alphas. */
const MIN_ALPHA = 0.1
const MAX_ALPHA = 0.5

/**
 * The norm of the compared cells: their median, plus the unit their distance
 * is measured in. `null` when fewer than three cells carry a value — two
 * points have no «usual».
 *
 * @param {Iterable<number|null>} values
 * @returns {{median: number, unit: number}|null}
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
  // A norm of zero (a card that usually sells nothing) has no «percent of it»;
  // the widest value in the set is the yardstick instead.
  const unit = Math.abs(median) || Math.max(...finite.map(Math.abs)) || 1
  return { median, unit }
}

/**
 * How strongly a cell departs from the norm: 0 inside the normal band, rising
 * softly towards 1, signed — positive above the norm, negative below.
 *
 * @param {number|null} value
 * @param {{median: number, unit: number}|null} norm
 * @param {{count?: boolean}} [options] `count` widens the band to ±√norm.
 * @returns {number|null} `null` when there is nothing to place.
 */
export function departure(value, norm, { count = false } = {}) {
  if (value === null || value === undefined || !Number.isFinite(value) || !norm) return null
  const distance = value - norm.median
  const band = Math.max(
    NORMAL_BAND * Math.abs(norm.median),
    count ? Math.sqrt(Math.max(norm.median, 1)) : 0,
  )
  const beyond = Math.abs(distance) - band
  if (beyond <= 0) return 0
  return Math.sign(distance) * Math.tanh(beyond / norm.unit / SOFTNESS)
}

/**
 * The background for a cell, or `''` for none.
 *
 * Built from the design tokens' channel triples, so the heatmap follows the
 * palette rather than carrying colours of its own.
 *
 * @param {number|null} strength From {@link departure}.
 * @param {'up'|'down'|'neutral'} direction
 * @returns {string}
 */
export function heatColor(strength, direction) {
  if (strength === null || strength === 0) return ''
  const alpha = (MIN_ALPHA + (MAX_ALPHA - MIN_ALPHA) * Math.abs(strength)).toFixed(3)
  if (direction === 'neutral') return `rgb(var(--ui-action-rgb) / ${alpha})`
  const better = direction === 'down' ? strength < 0 : strength > 0
  return `rgb(var(${better ? '--ui-pos-rgb' : '--ui-neg-rgb'}) / ${alpha})`
}
