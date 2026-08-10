/**
 * How a day cell is painted while a range is being picked.
 *
 * Split out of `PeriodSelector` because it is pure presentation of a
 * (start, end, hover, phase) tuple and knows nothing about a popover. The
 * subtlety it carries: while the SECOND endpoint is still being chosen there is
 * no committed range yet, so the day under the cursor stands in for it —
 * otherwise the calendar would give no feedback at all until the second click
 * landed. Dates are compared as ISO strings, which sort correctly by date.
 */

/**
 * The range currently in effect, including the live hover preview while picking.
 *
 * @param {{start: string|null, end: string|null, hover: string|null, phase: string}} state
 * @returns {{lo: string|null, hi: string|null}} Ordered endpoints — the user may
 *   pick the later day first, and every consumer wants them the right way round.
 */
export function effectiveRange({ start, end, hover, phase }) {
  const resolvedEnd = phase === 'end' ? hover || end : end
  if (!start || !resolvedEnd) return { lo: start || null, hi: null }
  return start <= resolvedEnd ? { lo: start, hi: resolvedEnd } : { lo: resolvedEnd, hi: start }
}

/** Whether a day is one of the range's two endpoints. */
export function isEndpoint(iso, { lo, hi }) {
  return iso === lo || iso === hi
}

/**
 * Wrapper (range-band) classes: the soft action band connecting the endpoints.
 *
 * Drawn on the WRAPPER rather than the day button so the band runs edge to edge
 * between days instead of breaking at every cell.
 */
export function wrapClass(cell, { lo, hi }) {
  if (!lo || !hi || lo === hi) return ''
  if (cell.iso < lo || cell.iso > hi) return ''
  const rounded = cell.iso === lo ? 'rounded-l-full' : cell.iso === hi ? 'rounded-r-full' : ''
  return `bg-action/10 ${rounded}`
}

/** Day-number button classes: solid action endpoints, subtle in-between/hover. */
export function btnClass(cell, range, todayIso) {
  if (cell.disabled) return 'text-border-subtle cursor-not-allowed'
  if (isEndpoint(cell.iso, range)) return 'bg-action text-white font-semibold shadow-soft'
  const { lo, hi } = range
  const inside = lo && hi && cell.iso > lo && cell.iso < hi
  const base = inside ? 'text-action' : cell.inMonth ? 'text-primary' : 'text-muted'
  const todayRing = cell.iso === todayIso ? 'ring-1 ring-inset ring-action/40' : ''
  return `${base} ${todayRing} hover:bg-action/15`
}
