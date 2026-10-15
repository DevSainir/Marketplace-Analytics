/**
 * Moscow time — the one clock the whole service shows.
 *
 * WB runs in Moscow time and the seller reads our pages next to figures from
 * the WB cabinet, so a stamp in the browser's own zone would put the two a few
 * unexplained hours apart (Бишкек is three ahead). Every instant the UI prints
 * goes through here, and every printed time of day says «МСК» so the reader
 * never has to guess which clock it is.
 *
 * Calendar dates that come from the API as `YYYY-MM-DD` are not instants and
 * need none of this: they are already days.
 */

export const MOSCOW_TZ = 'Europe/Moscow'

/** An ISO string, epoch ms or Date as a Date, or `null` when it is not one. */
function instantOf(value) {
  if (value === null || value === undefined || value === '') return null
  const ms =
    value instanceof Date ? value.getTime() : typeof value === 'number' ? value : Date.parse(value)
  return Number.isNaN(ms) ? null : new Date(ms)
}

/**
 * An instant on the Moscow clock, «14 окт., 10:47 МСК».
 *
 * `options` are the `toLocaleString` fields to show. «МСК» is appended whenever
 * they include the hour; a bare date gets no label, the day being the same
 * thing it would be in the WB cabinet.
 *
 * @param {string|number|Date|null} value The instant.
 * @param {Intl.DateTimeFormatOptions} options Fields to print.
 * @param {string} [fallback] What to print when there is no instant.
 * @returns {string} The stamp.
 */
export function formatMoscow(value, options, fallback = '—') {
  const at = instantOf(value)
  if (!at) return fallback
  const text = at.toLocaleString('ru-RU', { ...options, timeZone: MOSCOW_TZ })
  return 'hour' in options ? `${text} МСК` : text
}

/**
 * The Moscow calendar day of an instant, `YYYY-MM-DD` — «today» for the whole
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

/** «14.10.2026» — the Moscow day of an instant, in the short form lists use. */
export function formatMoscowDate(value, fallback = '—') {
  return formatMoscow(value, { day: '2-digit', month: '2-digit', year: 'numeric' }, fallback)
}
