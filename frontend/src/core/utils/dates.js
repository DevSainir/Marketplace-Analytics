/** Date helpers for the API's ISO (YYYY-MM-DD) query params. */

/**
 * Format a Date as YYYY-MM-DD in the **local** timezone.
 *
 * `toISOString()` would render UTC — between 00:00 and 03:00 Moscow time that
 * is still "yesterday", which silently shifts the analysis window.
 */
export function isoLocalDate(date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

/** Local YYYY-MM-DD for `days` days ago (0 = today). */
export function isoDaysAgo(days) {
  const date = new Date()
  date.setDate(date.getDate() - days)
  return isoLocalDate(date)
}

/**
 * Widest analysis window the API will answer for, in days between the two ends.
 *
 * Mirrors `backend/src/modules/monitoring/constants.py#MAX_WINDOW_DAYS`. It is
 * a bound on the work one request can demand — an unbounded `date_from` was a
 * memory and latency problem — and it is repeated here so the UI can say so
 * before asking, rather than showing the seller a failed request for a range
 * the calendar let them pick.
 */
export const MAX_WINDOW_DAYS = 366

/** Whole days between two ISO dates, the way the API counts a window. */
export function daysBetween(fromIso, toIso) {
  const from = new Date(`${fromIso}T00:00:00Z`)
  const to = new Date(`${toIso}T00:00:00Z`)
  return Math.round((to - from) / 86_400_000)
}
