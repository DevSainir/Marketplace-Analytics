/**
 * The words every date in the app is written with, and the two ways a day is
 * printed: "11 Jul 2026" in full and "11 Jul" where the year is the page's.
 *
 * Day first and the month as a word, never as a number: "07/11" reads as two
 * different days depending on which side of the Atlantic the reader is from,
 * and "11 Jul" reads as one. The names are spelled out here rather than taken
 * from `Intl`, which abbreviates September as "Sept" in British English and
 * puts the month first in American.
 */

/** Monday-first, matching the grid the picker draws. */
export const WEEKDAYS = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']

/** Sunday-first, as `Date.getDay()` counts. */
export const WEEKDAY_NAMES = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

export const MONTHS = [
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December',
]

export const MONTHS_SHORT = MONTHS.map((name) => name.slice(0, 3))

/** "2026-07-11" → "11 Jul 2026": how every date picker in the app writes a day. */
export function formatDay(iso) {
  if (!iso) return '—'
  const [y, m, d] = iso.split('-')
  return `${Number(d)} ${MONTHS_SHORT[Number(m) - 1]} ${y}`
}

/** "2026-07-11" → "11 Jul": a day inside a period the page already dates. */
export function formatDayShort(iso) {
  if (!iso) return '—'
  const [, m, d] = iso.split('-')
  return `${Number(d)} ${MONTHS_SHORT[Number(m) - 1]}`
}

/** "2026-07-11" → "Sat": the weekday of a calendar day, whatever the browser's zone. */
export function weekdayOf(iso) {
  const [y, m, d] = iso.split('-').map(Number)
  return WEEKDAY_NAMES[new Date(Date.UTC(y, m - 1, d)).getUTCDay()]
}
