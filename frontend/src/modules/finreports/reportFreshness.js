/**
 * The words under the P&L header: why the statement stops where it does.
 *
 * WB publishes the weekly realization report on no fixed day and no fixed hour,
 * so a statement whose last week ended nine days ago is usually correct and
 * occasionally a dead harvester. On a page that shows only numbers the two are
 * indistinguishable — in August 2026 the finance harvest crashed for three days
 * and nobody noticed, because "the figures stop at last Sunday" is exactly what
 * a quiet week looks like.
 *
 * Two facts fix that, and neither works alone: **what we hold** (which report is
 * newest on file and when we pulled it) and **when we last asked** (what the
 * hourly gate found, and the moment it found it). «Новых отчётов нет» means
 * nothing without «и мы спросили 12 минут назад».
 *
 * The rules this file exists to keep:
 *
 * * **A check that FAILED is never phrased as "nothing new."** WB not answering
 *   is an unanswered question; dressing it as reassurance is the exact failure
 *   the line was added to prevent. It says the data may be incomplete.
 * * **Staleness is the signal.** Minutes and hours up to a day, an absolute date
 *   beyond it, and a warning tone once nobody has asked in over a day or the
 *   last question went unanswered. A quiet week is normal and reads as normal.
 * * **Name the period we hold, not the probe window.** That string is what the
 *   seller matches against WB's own отчёты page, so it keeps WB's day-month
 *   shape.
 * * **A provisional day is named as provisional.** Since the daily tail landed,
 *   the statement includes days no weekly settlement report covers yet — WB
 *   serves a per-day report the following morning. Saying only «Последний отчёт
 *   WB: 14-20 сен» over figures that run to the 22nd contradicts the page;
 *   folding those days INTO that period would claim a settlement document WB has
 *   not issued. So they get their own clause and the word «предварительно».
 * * **Timezones.** `harvested_at` / `checked_at` are UTC *instants*: day and
 *   time are read off one local `Date` together, or a 23:14Z harvest prints its
 *   day and its time a day apart in Moscow. A report's period is a calendar
 *   date and is never put through `Date` at all.
 */

/** Genitive short month names, WB's own shape in «10–16 авг». */
const MONTHS = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']

const MINUTE_MS = 60000
const HOUR_MS = 60 * MINUTE_MS
const DAY_MS = 24 * HOUR_MS

/**
 * Split a `YYYY-MM-DD` calendar date without going through `Date`.
 *
 * A report's period is a calendar day, not an instant: `new Date('2026-08-16')`
 * is midnight UTC and prints as the 15th anywhere west of Greenwich. Nothing
 * here needs a timezone, so nothing here gets one.
 *
 * @param {string|null|undefined} iso
 * @returns {{day: number, month: number}|null}
 */
function calendarDay(iso) {
  if (typeof iso !== 'string') return null
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso)
  if (!match) return null
  const month = Number(match[2]) - 1
  if (month < 0 || month > 11) return null
  return { day: Number(match[3]), month }
}

/** «16 авг» for one calendar date, or `''` when it is not one. */
function dayMonth(iso) {
  const parsed = calendarDay(iso)
  return parsed ? `${parsed.day} ${MONTHS[parsed.month]}` : ''
}

/**
 * The period a report covers, in WB's own shape.
 *
 * Same month collapses to «10–16 авг»; a week straddling two keeps both
 * («28 июл – 3 авг»). A header with only one endpoint — WB serves them — says
 * which endpoint it has rather than inventing the other.
 *
 * @param {{date_from: string|null, date_to: string|null}} report
 * @returns {string} The period, or `''` when WB stated none.
 */
export function formatPeriod(report) {
  const from = calendarDay(report?.date_from)
  const to = calendarDay(report?.date_to)
  if (from && to) {
    return from.month === to.month
      ? `${from.day}–${to.day} ${MONTHS[to.month]}`
      : `${from.day} ${MONTHS[from.month]} – ${to.day} ${MONTHS[to.month]}`
  }
  if (to) return `по ${dayMonth(report.date_to)}`
  if (from) return `с ${dayMonth(report.date_from)}`
  return ''
}

/**
 * An instant as «18 авг, 06:14» in the reader's own timezone.
 *
 * Day and time come off the SAME local `Date`. Formatting them from different
 * sources is how a 23:14Z harvest ends up printed with Moscow's time and UTC's
 * day — off by one, and only for the three hours where anyone would notice.
 *
 * @param {string} iso UTC instant.
 * @returns {string} The formatted instant, or `''` when it is not one.
 */
export function formatInstant(iso) {
  const at = new Date(iso)
  if (Number.isNaN(at.getTime())) return ''
  const time = `${String(at.getHours()).padStart(2, '0')}:${String(at.getMinutes()).padStart(2, '0')}`
  return `${at.getDate()} ${MONTHS[at.getMonth()]}, ${time}`
}

/**
 * How long ago an instant was — the half that makes the rest mean anything.
 *
 * Plain minutes and hours inside a day, an absolute date past it: "проверено
 * 2 дня назад" and "проверено 3 сент" say the same thing, and only the second
 * one is checkable against anything.
 *
 * @param {string} iso UTC instant.
 * @param {Date} now Reference time (injected so this stays pure).
 * @returns {string} Elapsed phrase, or `''` when the instant is unreadable.
 */
export function formatElapsed(iso, now) {
  const at = new Date(iso)
  if (Number.isNaN(at.getTime())) return ''
  const elapsed = now.getTime() - at.getTime()
  // A future instant is clock skew between the server and this browser, not a
  // fact about the harvest. «через 3 минуты» would read as a broken page.
  if (elapsed < MINUTE_MS) return 'только что'
  if (elapsed < HOUR_MS) return `${Math.floor(elapsed / MINUTE_MS)} мин назад`
  if (elapsed < DAY_MS) return `${Math.floor(elapsed / HOUR_MS)} ч назад`
  return `${at.getDate()} ${MONTHS[at.getMonth()]}`
}

/**
 * What the last freshness check found, in words.
 *
 * `wb_empty` is the only outcome allowed to say «нового ничего нет», and it
 * names the period we hold rather than the days that were probed — the seller
 * compares that string against WB's отчёты page, which lists periods.
 *
 * @param {{outcome: string}} check
 * @param {string} held The period we hold, already formatted.
 * @returns {string}
 */
function describeCheck(check, held) {
  switch (check.outcome) {
    case 'wb_empty':
      return held
        ? `Wildberries пока не опубликовал отчёт новее ${held}`
        : 'Wildberries пока не опубликовал ничего новее'
    case 'up_to_date':
      return 'Отчёты загружены по вчерашний день'
    case 'wb_has_new':
      return 'Wildberries опубликовал новый отчёт — загружаем'
    case 'never_harvested':
      return 'Загружаем всё, что есть у Wildberries'
    case 'probe_failed':
      // Never «новых отчётов нет». WB did not answer; saying nothing is new
      // would report silence as reassurance.
      return 'Не удалось спросить Wildberries — данные могут быть неполными'
    case 'rate_blocked':
      // Also not reassurance, and deliberately not phrased as our failure:
      // WB has shut the endpoint, and pressing «Обновить» again is the one
      // thing that makes it worse — a request inside an open block restarts
      // it longer.
      return 'Wildberries временно ограничил доступ — ждём и загрузим сами'
    default:
      // An outcome this build does not know is not an outcome it may narrate.
      return ''
  }
}

/**
 * Build the freshness line from a harvest-state payload.
 *
 * @param {{latest_report: object|null, last_check: object|null,
 *   provisional_through: string|null}|null} state
 *   `GET /v1/finreports/harvest`, or `null` when it could not be fetched.
 * @param {Date} [now] Reference time; injected so the result is testable.
 * @returns {{text: string, tone: 'muted'|'warning'}|null} The line, or `null`
 *   when there is nothing honest to say — in which case the page shows nothing
 *   at all. A footnote must not shout over the statement it annotates.
 */
export function describeFreshness(state, now = new Date()) {
  if (!state) return null
  const report = state.latest_report ?? null
  const check = state.last_check ?? null
  if (!report && !check) return null

  const held = report ? formatPeriod(report) : ''
  const parts = []

  if (report) {
    parts.push(held ? `Последний отчёт WB: ${held}` : 'Последний отчёт WB: период не указан')
    const loaded = formatInstant(report.harvested_at)
    if (loaded) parts.push(`загружен ${loaded}`)
  } else {
    parts.push('Отчётов WB пока нет')
  }

  // The backend sends this only when the tail actually reaches past the settled
  // period, so there is no «plus nothing» case to suppress here.
  const provisional = dayMonth(state.provisional_through)
  if (provisional) parts.push(`предварительно по ${provisional}`)

  // Missing entirely — never checked, the record expired, or it came back
  // unreadable. All three mean the same thing and none of them is reassuring:
  // a stale probe is precisely the evidence that the harvester stopped.
  if (!check) {
    parts.push('неизвестно, когда мы в последний раз спрашивали Wildberries')
    return { text: parts.join(' · '), tone: 'warning' }
  }

  const said = describeCheck(check, held)
  if (said) parts.push(said)
  const elapsed = formatElapsed(check.checked_at, now)
  if (elapsed) parts.push(`проверено ${elapsed}`)

  const checkedAt = new Date(check.checked_at)
  const stale = Number.isNaN(checkedAt.getTime()) || now.getTime() - checkedAt.getTime() >= DAY_MS
  return {
    text: parts.join(' · '),
    tone:
      check.outcome === 'probe_failed' || check.outcome === 'rate_blocked' || stale
        ? 'warning'
        : 'muted',
  }
}
