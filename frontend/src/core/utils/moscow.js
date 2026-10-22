/**
 * Moscow time — the one clock the whole service shows.
 *
 * WB runs in Moscow time and the seller reads our pages next to figures from
 * the WB seller portal, so a stamp in the browser's own zone would put the two
 * a few unexplained hours apart (Bishkek is three ahead). Every instant the UI
 * prints goes through here, and every printed time of day says "MSK" so the
 * reader never has to guess which clock it is.
 *
 * Calendar dates that come from the API as `YYYY-MM-DD` are not instants and
 * need none of this: they are already days.
 */

import { MONTHS, MONTHS_SHORT } from '@/core/utils/calendarWords'

export const MOSCOW_TZ = 'Europe/Moscow'

/** An ISO string, epoch ms or Date as a Date, or `null` when it is not one. */
function instantOf(value) {
  if (value === null || value === undefined || value === '') return null
  const ms =
    value instanceof Date ? value.getTime() : typeof value === 'number' ? value : Date.parse(value)
  return Number.isNaN(ms) ? null : new Date(ms)
}

/** The month as a word: in full when asked for `long`, abbreviated otherwise. */
function monthWord(number, style) {
  return (style === 'long' ? MONTHS : MONTHS_SHORT)[Number(number) - 1]
}

/**
 * An instant on the Moscow clock, "14 Oct, 10:47 MSK".
 *
 * `options` name the `Intl.DateTimeFormat` fields to show; they are assembled
 * day first with the month as a word, however the month was asked for — a
 * `2-digit` month prints "Oct" too, because "10/14" means a different day to
 * half the readers. "MSK" is appended whenever the hour is shown; a bare date
 * gets no label, the day being the same thing it would be in the WB portal.
 *
 * @param {string|number|Date|null} value The instant.
 * @param {Intl.DateTimeFormatOptions} options Fields to print.
 * @param {string} [fallback] What to print when there is no instant.
 * @returns {string} The stamp.
 */
export function formatMoscow(value, options, fallback = '—') {
  const at = instantOf(value)
  if (!at) return fallback
  // The month is read as a number and named here, so every style comes out
  // the same way round.
  const fields = { ...options, timeZone: MOSCOW_TZ, hourCycle: 'h23' }
  if (fields.month) fields.month = 'numeric'
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat('en-US', fields)
      .formatToParts(at)
      .map((part) => [part.type, part.value]),
  )
  const date = [
    parts.day && String(Number(parts.day)),
    parts.month && monthWord(parts.month, options.month),
    parts.year,
  ]
    .filter(Boolean)
    .join(' ')
  const time = 'hour' in options ? `${parts.hour}:${parts.minute ?? '00'} MSK` : ''
  return [date, time].filter(Boolean).join(', ')
}

/**
 * The Moscow calendar day of an instant, `YYYY-MM-DD` — "today" for the whole
 * service, wherever the browser is.
 *
 * @param {string|number|Date} [value] The instant; now by default.
 * @returns {string} The day, or `''` when it is not an instant.
 */
export function moscowIsoDate(value = new Date()) {
  const at = instantOf(value)
  if (!at) return ''
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat('en-US', {
      timeZone: MOSCOW_TZ,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    })
      .formatToParts(at)
      .map((part) => [part.type, part.value]),
  )
  return `${parts.year}-${parts.month}-${parts.day}`
}

/** "14 Oct 2026" — the Moscow day of an instant, in the short form lists use. */
export function formatMoscowDate(value, fallback = '—') {
  return formatMoscow(value, { day: 'numeric', month: 'short', year: 'numeric' }, fallback)
}
