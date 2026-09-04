/**
 * The P&L period as it survives a page reload.
 *
 * Split out of the store because remembering a period turned out to be three
 * decisions, not one: what to write down, how long it stays true, and where a
 * remembered window lands once WB has published weeks it never saw. The store
 * keeps the refs; this file keeps the memory.
 */

/** Where the chosen period lives between visits. */
const PERIOD_KEY = 'finreports:period'

/** Default span on first ever open: the last week (7 settled days). */
export const DEFAULT_DAYS = 7

/**
 * How long a chosen period outlives the choice.
 *
 * It used to outlive it indefinitely, which is wrong for a window a seller
 * looks at daily: a range picked once kept the page on an old week for as long
 * as the browser remembered it, with newer settlement reports sitting unread
 * behind it. A day is where «the period I picked» stops describing the saved
 * value and it becomes a stale default nobody chose.
 */
const PERIOD_TTL_MS = 24 * 60 * 60 * 1000

/**
 * Move an ISO day along the calendar.
 *
 * Deliberately not `new Date(iso)` plus local formatting: `new Date('2026-08-30')`
 * is UTC midnight, so reading it back in a calendar behind UTC lands on the day
 * before. Settlement dates are calendar days with no time in them, so the
 * arithmetic stays in UTC from end to end.
 *
 * @param {string} iso Day to move, `YYYY-MM-DD`.
 * @param {number} days Offset in days; negative moves back.
 * @returns {string} The shifted day, `YYYY-MM-DD`.
 */
export function shiftIsoDate(iso, days) {
  return new Date(Date.parse(`${iso}T00:00:00Z`) + days * 86400000).toISOString().slice(0, 10)
}

/**
 * How many days a window covers, both ends inclusive.
 *
 * @param {string} from First day, `YYYY-MM-DD`.
 * @param {string} to Last day, `YYYY-MM-DD`.
 * @returns {number} Day count, 1 for a single-day window.
 */
export function spanDays(from, to) {
  const ms = Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)
  return Math.round(ms / 86400000) + 1
}

/**
 * The saved period, or `null` when there is none or it no longer counts.
 *
 * An entry without a stamp was written by a build that pinned the period
 * indefinitely — the very thing the TTL exists to end — so it is dropped rather
 * than grandfathered in. An expired entry is removed on the way out, so a
 * seller who does not come back for a week is not carrying it around.
 *
 * @returns {{from: string, to: string, span: ?{from: string, to: string}, saved_at: string}|null}
 */
export function readSavedPeriod() {
  try {
    const saved = JSON.parse(localStorage.getItem(PERIOD_KEY) ?? 'null')
    if (!saved?.from || !saved?.to) return null
    const savedAt = Date.parse(saved.saved_at ?? '')
    if (!savedAt || Date.now() - savedAt > PERIOD_TTL_MS) {
      localStorage.removeItem(PERIOD_KEY)
      return null
    }
    return saved
  } catch {
    return null
  }
}

/**
 * Write down a chosen period.
 *
 * `span` is the harvested history as it stood at the moment of the choice, and
 * it is the whole reason a restore can tell «последняя неделя» from a window
 * that merely happens to end on that day. Without it a period coming back a day
 * later cannot know whether it was ever meant to follow the data.
 *
 * `savedAt` is passed in rather than stamped here so that following the data
 * does not read as a fresh choice and buy the window another day.
 *
 * @param {string} from First day of the window.
 * @param {string} to Last day of the window.
 * @param {?{date_from: string, date_to: string}} span Harvested span at the time.
 * @param {number} [savedAt] Epoch ms of the choice; defaults to now.
 */
export function writeSavedPeriod(from, to, span, savedAt = Date.now()) {
  try {
    localStorage.setItem(
      PERIOD_KEY,
      JSON.stringify({
        from,
        to,
        span: span ? { from: span.date_from, to: span.date_to } : null,
        saved_at: new Date(savedAt).toISOString(),
      }),
    )
  } catch {
    /* private mode / storage disabled — the period just won't persist */
  }
}

/**
 * Where a saved period lands now, given the history harvested since.
 *
 * The rule the store already applies to a period on screen when a harvest
 * arrives, applied to one coming back from storage: a window that ENDED at the
 * newest settled day *of its own time* meant «последняя неделя», so it follows
 * the data; one that stopped short of that day was chosen for the dates it
 * names and comes back untouched. Without this the saved period could only ever
 * age — the hourly harvest kept bringing weeks that a reload could not reach.
 *
 * Persists the move, keeping the original stamp, so the next reload starts from
 * where the window actually is.
 *
 * @param {{from: string, to: string, span: ?{from: string, to: string}, saved_at: string}} saved
 * @param {?{date_from: string, date_to: string}} span The harvested span now.
 * @returns {{from: string, to: string}} The window to show.
 */
export function restoreSavedPeriod(saved, span) {
  const before = saved.span
  const wasOnLatest = Boolean(before) && saved.to === before.to
  if (!wasOnLatest || !span || span.date_to === before.to) {
    return { from: saved.from, to: saved.to }
  }
  // «Вся история» is extended, not slid: it is anchored at both ends, and
  // preserving its LENGTH would walk its start forward and quietly drop the
  // oldest days from the total.
  const from =
    saved.from === before.from
      ? span.date_from
      : shiftIsoDate(span.date_to, -(spanDays(saved.from, saved.to) - 1))
  writeSavedPeriod(from, span.date_to, span, Date.parse(saved.saved_at))
  return { from, to: span.date_to }
}
