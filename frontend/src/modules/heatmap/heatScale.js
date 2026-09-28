/**
 * The heatmap's colour: where a value sits between the worst and the best of
 * the cells it is compared with, turned into a tint.
 *
 * Pure presentation — every figure is the backend's, and this only decides how
 * loudly to paint it. Two things carry the meaning:
 *
 * * **Direction.** «Больше — лучше» (заказы, выручка) paints the top of the
 *   range green; «меньше — лучше» (ДРР, CPC, CPO) paints the BOTTOM green. A
 *   price or a stock level has no better end, so it is painted in the action
 *   hue by magnitude alone rather than pretending to be good or bad.
 * * **The range.** «По строке» compares a row with itself — where did this card
 *   dip; «по всей таблице» puts every row on one scale — which cards lead. The
 *   caller picks which cells form the range; this file never guesses.
 *
 * The middle of the range is left unpainted on purpose: a heatmap where every
 * cell is some shade of colour has no signal, and the eye should land on the
 * ends.
 */

/** Strongest tint, as an alpha: dark enough to read at a glance, light enough
 *  that the number printed on it stays legible. */
const MAX_ALPHA = 0.5

/** How far from the middle a cell must sit before it is painted at all. */
const DEAD_ZONE = 0.04

/**
 * Min and max of the finite values in `values`, or `null` when there are none.
 *
 * @param {Iterable<number|null>} values
 * @returns {{min: number, max: number}|null}
 */
export function rangeOf(values) {
  let min = Infinity
  let max = -Infinity
  for (const value of values) {
    if (value === null || value === undefined || !Number.isFinite(value)) continue
    if (value < min) min = value
    if (value > max) max = value
  }
  return min === Infinity ? null : { min, max }
}

/**
 * Where `value` sits in `range`, as 0 (worst) … 1 (best).
 *
 * For a neutral metric it is plain magnitude: 0 at the minimum, 1 at the
 * maximum. `null` when there is nothing to place — no value, no range, or a
 * range with no spread (every cell equal has no better or worse one).
 *
 * @param {number|null} value
 * @param {{min: number, max: number}|null} range
 * @param {'up'|'down'|'neutral'} direction
 * @returns {number|null}
 */
export function heatPosition(value, range, direction) {
  if (value === null || value === undefined || !Number.isFinite(value) || !range) return null
  const spread = range.max - range.min
  if (spread <= 0) return null
  const share = Math.min(1, Math.max(0, (value - range.min) / spread))
  return direction === 'down' ? 1 - share : share
}

/**
 * The background for a cell at `position`, or `''` for no tint.
 *
 * Built from the design tokens' channel triples, so the heatmap follows the
 * palette rather than carrying colours of its own.
 *
 * @param {number|null} position From {@link heatPosition}.
 * @param {'up'|'down'|'neutral'} direction
 * @returns {string}
 */
export function heatColor(position, direction) {
  if (position === null) return ''
  if (direction === 'neutral') {
    const alpha = position * MAX_ALPHA * 0.7
    return alpha < 0.02 ? '' : `rgb(var(--ui-action-rgb) / ${alpha.toFixed(3)})`
  }
  const offset = position - 0.5
  if (Math.abs(offset) < DEAD_ZONE) return ''
  const alpha = Math.min(1, Math.abs(offset) * 2) * MAX_ALPHA
  const channel = offset > 0 ? '--ui-pos-rgb' : '--ui-neg-rgb'
  return `rgb(var(${channel}) / ${alpha.toFixed(3)})`
}
