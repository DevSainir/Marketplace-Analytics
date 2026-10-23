/**
 * Where the "good / bad" bounds lie in the per-article report.
 *
 * Color in the table is not decoration but an attention filter: in a report of
 * forty rows and twenty columns, an unaided eye reads the first three rows. So
 * only a figure that has left its bounds is highlighted, and everything within
 * the usual spread stays plain text — tint half the table and nothing stands
 * out.
 *
 * The bounds were calibrated against an observed 90-day distribution over a
 * catalog of a few dozen articles, not made up: the red bound sits at about
 * the top decile, the green one at about the bottom quartile (the other way
 * round for "higher is better"), so a typical report highlights a few rows, not
 * everything. The same calibration was repeated per price base and for the size
 * buyout, which gets its own bounds.
 *
 * DRR has no green at all and turns red only above 20 % on either base — a
 * product decision: a low DRR is no achievement (often the ads simply were not
 * running), and up to 20 % advertising is normal. `good: null` means there is no
 * "good" side. The sample is small (p10 and p90 rest on 2–3 articles): measure
 * again on the next revision. Margin keeps "bad" at a meaningful boundary (a
 * loss), not at a percentile.
 *
 * ROI used to tint half the table: red sat below 100 % with the explanation "the
 * batch has not paid off", which is wrong. ROI is profit over cost price, and
 * any ROI above zero means the batch has already paid off and earned on top. Red
 * is now below 30 % — "weak", also a product decision.
 *
 * SPP is deliberately not highlighted: it is a discount WB pays for, it does not
 * affect the seller's money, and it has no "good" or "bad" side.
 */

/**
 * Bounds per metric. `good`/`bad` are thresholds in the same units the value
 * arrives in (percentages as 12.6, not 0.126). `higherIsBetter` says which side
 * of the bounds is bad.
 */
export const BOUNDS = {
  /** Returns: the share of bought-out units that came back. Lower is better. */
  returnPct: { good: 10, bad: 21, higherIsBetter: false },
  /** Logistics share of revenue — the heaviest line when the buyout rate is low. */
  logisticsPct: { good: 18, bad: 38, higherIsBetter: false },
  /**
   * DRR — advertising share of revenue. `zeroIsAbsent`: zero here almost always
   * means "no ads were running", not "ads ran perfectly cheaply", and green on
   * it would tint half the report for something nobody did.
   */
  advertisingPct: { good: null, bad: 20, higherIsBetter: false, zeroIsAbsent: true },
  /** Margin % — net profit over revenue. Zero is already bad. */
  profitPct: { good: 32, bad: 0, higherIsBetter: true },
  /** Product ROI — profit over cost price. Below 30 % is weak (above zero has paid off). */
  roi: { good: 200, bad: 30, higherIsBetter: true },
  /** Article buyout — WB's funnel buyout rate: buyouts over settled orders. */
  buyoutPct: { good: 30, bad: 16, higherIsBetter: true },
  /** Size buyout — a different measure (sold over deliveries), hence its own bounds. */
  sizeBuyoutPct: { good: 35, bad: 20, higherIsBetter: true },
}

/**
 * Bounds for revenue shares when revenue is taken at the buyer's price (after
 * SPP). The same logistics over a smaller revenue is a larger percentage, and
 * the seller's-price bounds would tint noticeably more rows on this base. Only
 * for metrics divided by revenue; the rest come from {@link BOUNDS}.
 */
export const PAID_BOUNDS = {
  logisticsPct: { good: 22, bad: 46, higherIsBetter: false },
  advertisingPct: { good: null, bad: 20, higherIsBetter: false, zeroIsAbsent: true },
  profitPct: { good: 39, bad: 0, higherIsBetter: true },
}

/** A metric's bounds for the selected price base (`'seller'` or `'paid'`). */
function boundsOf(metric, base) {
  return (base === 'paid' && PAID_BOUNDS[metric]) || BOUNDS[metric]
}

/**
 * Where the value landed: `'positive'`, `'negative'` or `''` (within bounds).
 *
 * @param {string} metric A key of {@link BOUNDS}.
 * @param {number|string|null|undefined} value
 * @param {string} [base] Price base of the share — `'seller'` (default) or `'paid'`.
 * @returns {'positive'|'negative'|''}
 */
export function tone(metric, value, base = 'seller') {
  const bounds = boundsOf(metric, base)
  if (!bounds || value === null || value === undefined || value === '') return ''
  const n = Number(value)
  if (!Number.isFinite(n)) return ''
  if (bounds.zeroIsAbsent && n === 0) return ''
  if (bounds.higherIsBetter) {
    if (n < bounds.bad) return 'negative'
    return n >= bounds.good ? 'positive' : ''
  }
  if (n > bounds.bad) return 'negative'
  return bounds.good !== null && n <= bounds.good ? 'positive' : ''
}

/** The text class for the same check — what goes onto the cell. */
export function toneClass(metric, value, base = 'seller') {
  const t = tone(metric, value, base)
  if (t === 'positive') return 'text-status-positive'
  if (t === 'negative') return 'text-status-negative'
  return ''
}

/**
 * Money: only a negative is highlighted. A sum has no bounds — "a lot" depends
 * on the article's scale, but a loss is bad at any scale.
 *
 * @param {number|string|null|undefined} value
 */
export function amountClass(value) {
  if (value === null || value === undefined || value === '') return ''
  return Number(value) < 0 ? 'text-status-negative' : ''
}
