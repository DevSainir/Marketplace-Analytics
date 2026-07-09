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
