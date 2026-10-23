/**
 * The words under the P&L header: why the statement stops where it does.
 *
 * WB publishes the weekly settlement report on no fixed day and no fixed hour,
 * so a statement whose last week ended nine days ago is usually correct and
 * occasionally a dead harvester. On a page that shows only numbers the two are
 * indistinguishable — in August 2026 the finance harvest crashed for three days
 * and nobody noticed, because "the figures stop at last Sunday" is exactly what
 * a quiet week looks like.
 *
 * Two facts fix that, and neither works alone: **what we hold** (the newest
 * weekly report and how far the daily ones reach) and **what the hourly gate
 * found** the last time it asked WB.
 *
 * The rules this file exists to keep:
 *
 * * **A check that FAILED is never phrased as "nothing new."** WB not answering
 *   is an unanswered question; dressing it as reassurance is the exact failure
 *   the line was added to prevent. It says the data may be incomplete.
 * * **Staleness is the signal, and only staleness is shown.** A check younger
 *   than a day says nothing about its age — "checked 14 min ago" on every
 *   load was noise. Past a day the line turns to a warning and names the date
 *   of the last check, which is what a dead harvester looks like.
 * * **Name both kinds of report.** Since the daily tail landed the statement
 *   runs past the last weekly report: WB serves a per-day report the following
 *   morning. "Latest WB weekly report: 21–27 Sep" over figures that run
 *   to the 30th reads as a contradiction unless the line also says "daily
 *   through 30 Sep". Folding those days INTO the weekly period would claim a
 *   settlement document WB has not issued.
 * * **Timezones.** `checked_at` is a UTC *instant* and is read on the Moscow
 *   calendar (`core/utils/moscow.js`). A report's period is a calendar date and never goes through `Date`.
 */

import { MONTHS_SHORT as MONTHS } from '@/core/utils/calendarWords'
import { moscowIsoDate } from '@/core/utils/moscow'

/**
 * The ⓘ beside "ready, waiting for the API". WB shows the report in the WB
 * seller portal hours before its API serves it (12 Oct 2026: on the site by
 * 08:00, absent from the API at 08:05), and a seller who sees it there and not here
 * reads a broken harvest unless the page says why.
 */
export const AWAITED_HINT =
  'WB shows a report in the WB seller portal first and serves it to us later, usually a few hours on. We load it as soon as WB does. Or skip the wait: download the report from the WB seller portal and press "Upload report".'

/** Past this age the last check is stale, and the line says when it ran. */
const DAY_MS = 24 * 60 * 60 * 1000

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

/** "16 Aug" for one calendar date, or `''` when it is not one. */
function dayMonth(iso) {
  const parsed = calendarDay(iso)
  return parsed ? `${parsed.day} ${MONTHS[parsed.month]}` : ''
}

/**
 * The period a report covers, day first.
 *
 * Same month collapses to "10–16 Aug"; a week straddling two keeps both
 * ("28 Jul – 3 Aug"). A header with only one endpoint — WB serves them — says
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
  if (to) return `through ${dayMonth(report.date_to)}`
  if (from) return `from ${dayMonth(report.date_from)}`
  return ''
}

/**
 * The Moscow calendar day of an instant, "28 Sep" — when the last check ran.
 *
 * @param {string} iso UTC instant.
 * @returns {string} The day, or `''` when it is not an instant.
 */
export function formatCheckDay(iso) {
  const day = moscowIsoDate(iso)
  return day ? dayMonth(day) : ''
}

/**
 * The calendar day after `iso`, as `YYYY-MM-DD` — arithmetic on the calendar,
 * never on an instant, so no timezone can move it.
 */
function nextDay(iso) {
  const parsed = calendarDay(iso)
  if (!parsed) return ''
  const year = Number(iso.slice(0, 4))
  const next = new Date(Date.UTC(year, parsed.month, parsed.day + 1))
  return next.toISOString().slice(0, 10)
}

/** Today on the Moscow calendar, as `YYYY-MM-DD` — the service's one clock. */
function localToday(now) {
  return moscowIsoDate(now)
}

/**
 * What the last freshness check found, in words — or `''` when the line
 * already says it.
 *
 * `up_to_date` means we hold every report WB has formed, which "daily through
 * 30 Sep" already says. `wb_empty` names the first day we do not hold, and
 * only while that day is over: a report for today cannot exist yet, and
 * "hasn't published today's" would read as WB being late.
 *
 * @param {{outcome: string}} check
 * @param {string} heldThrough Last day the statement covers, `YYYY-MM-DD`.
 * @param {Date} now
 * @param {boolean} running Whether a harvest holds the lock right now.
 * @returns {string}
 */
function describeCheck(check, heldThrough, now, running) {
  switch (check.outcome) {
    case 'wb_empty': {
      const missing = nextDay(heldThrough)
      return missing && missing < localToday(now)
        ? `WB hasn't published the daily report for ${dayMonth(missing)} yet`
        : "WB hasn't published new reports yet"
    }
    case 'wb_has_new':
      // The verdict outlives the run: the walk records it again on success.
      // Once nothing is running the report is on the page, not "loading".
      return running ? 'WB published a new report — loading' : ''
    case 'never_harvested':
      return 'Loading reports from WB…'
    case 'probe_failed':
      // Never "nothing new". WB did not answer; saying nothing is new
      // would report silence as reassurance.
      return "WB didn't answer — newer reports may exist"
    case 'rate_blocked':
      // Also not reassurance, and deliberately not phrased as our failure:
      // WB has shut the endpoint, and pressing "Refresh" again is the one
      // thing that makes it worse — a request inside an open block restarts
      // it longer.
      return "WB is rate-limiting requests — we'll load once it lifts"
    default:
      // `up_to_date`, and any outcome this build does not know — which is not
      // an outcome it may narrate.
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
 * @returns {{text: string, tone: 'muted'|'warning', notes: Array<{text: string, hint?: string}>}|null}
 *   The line, plus `notes` — each a line of its own under it, with an optional
 *   ⓘ: a report the seller uploaded by hand, a report WB has formed and not yet
 *   served. Or `null`
 *   when there is nothing honest to say — in which case the page shows nothing
 *   at all. A footnote must not shout over the statement it annotates.
 */
export function describeFreshness(state, now = new Date()) {
  if (!state) return null
  const report = state.latest_report ?? null
  const check = state.last_check ?? null
  if (!report && !check) return null

  const parts = []
  if (report) {
    const held = formatPeriod(report)
    parts.push(`Latest WB weekly report: ${held || 'period not stated'}`)
    // The backend sends this only when the tail actually reaches past the
    // settled period, so there is no "plus nothing" case to suppress here.
    const daily = dayMonth(state.provisional_through)
    if (daily) parts.push(`daily through ${daily}`)
  } else if (check?.outcome !== 'never_harvested') {
    parts.push('No WB reports yet')
  }

  // Missing entirely — Redis did not answer, the record outlived its 30 days,
  // or it came back in a shape this build does not read. None is reassuring:
  // the second is precisely what a harvester dead for a month looks like.
  if (!check) {
    parts.push('Last WB check unknown — data may be incomplete')
    return { text: parts.join(' · '), tone: 'warning' }
  }

  const said = describeCheck(
    check,
    state.provisional_through || report?.date_to || '',
    now,
    Boolean(state.running),
  )
  // A report WB's calendar says is formed outranks "WB hasn't published": the
  // seller can see it on WB's site, so "not out yet" would read as a lie. Only
  // "loading" says more, and an unanswered or blocked check is still news.
  const awaited = formatPeriod(state.awaited_report ?? {})
  const loading = check.outcome === 'wb_has_new' && said
  const quiet = check.outcome === 'wb_empty' || check.outcome === 'up_to_date'
  // Each on a line of its own: appended to the first, the sentence ran past
  // what a reader takes in at a glance.
  const notes = []
  const uploaded = formatPeriod(state.uploaded_report ?? {})
  if (uploaded) {
    notes.push({
      text: `Report for ${uploaded} uploaded from a file — checked against WB once the API serves it`,
    })
  }
  if (awaited && !loading) {
    if (said && !quiet) parts.push(said)
    if (awaited !== uploaded) {
      notes.push({
        text: `Report for ${awaited} is ready, waiting for the API`,
        hint: AWAITED_HINT,
      })
    }
  } else if (said) {
    parts.push(said)
  }

  const checkedAt = new Date(check.checked_at)
  const stale = Number.isNaN(checkedAt.getTime()) || now.getTime() - checkedAt.getTime() >= DAY_MS
  const lastDay = formatCheckDay(check.checked_at)
  if (stale && lastDay) parts.push(`last WB check: ${lastDay}`)

  return {
    text: parts.join(' · '),
    tone:
      check.outcome === 'probe_failed' || check.outcome === 'rate_blocked' || stale
        ? 'warning'
        : 'muted',
    notes,
  }
}
