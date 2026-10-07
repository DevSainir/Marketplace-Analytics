/**
 * The period a page was left on, remembered for an hour.
 *
 * One rule for every page that picks a period, instead of each page's own: the
 * P&L used to keep its window for a day, the heatmap for twenty minutes, the
 * monitoring page only in its URL, and the summary and advertising pages not
 * at all. An hour survives a detour to another page or a reload and is gone by
 * the next working session, where yesterday's window would be a stale default
 * nobody chose.
 *
 * Kept per page AND per кабинет: a window picked on the P&L must not move the
 * monitoring page, and one кабинет's history says nothing about another's.
 *
 * A window that ended on the newest day the page had data for meant «the
 * latest N days», so it comes back moved onto the newest day there is now;
 * one that stopped short of it was chosen for the dates it names and comes
 * back as it was. Storage can be blocked or empty (a private window, cleared
 * site data), so every access is guarded and the page starts on its default.
 */
import { getWorkspaceId } from '@/core/api/axios'
import { shiftIso } from '@/core/utils/calendarModel'
import { daysBetween } from '@/core/utils/dates'

/** How long a chosen period outlives the choice. */
export const PERIOD_TTL_MS = 60 * 60 * 1000

const keyOf = (page) => `period:${page}:${getWorkspaceId() ?? 'none'}`

/**
 * Write down a chosen period.
 *
 * `edge` is the page's data as it stood at the moment of the choice — its
 * first and newest day — and it is the whole reason a restore can tell «the
 * latest week» from a window that merely ends on that day. `savedAt` is passed
 * in, not stamped here, so that following the data does not read as a fresh
 * choice and buy the window another hour.
 *
 * @param {string} page Which page's period this is, e.g. `'finreports'`.
 * @param {string} from First day of the window, ISO.
 * @param {string} to Last day of the window, ISO.
 * @param {{from?: string, to?: string}} [edge] The page's first and newest day; either may be empty.
 * @param {number} [savedAt] Epoch ms of the choice; defaults to now.
 */
export function rememberPeriod(page, from, to, edge = {}, savedAt = Date.now()) {
  try {
    localStorage.setItem(
      keyOf(page),
      JSON.stringify({
        from,
        to,
        edge: { from: edge.from ?? '', to: edge.to ?? '' },
        saved_at: savedAt,
      }),
    )
  } catch {
    // Storage refused: the page still works, it just will not remember.
  }
}

/** The stored entry, or `null` when there is none or it has expired. */
function readEntry(page) {
  try {
    const saved = JSON.parse(localStorage.getItem(keyOf(page)) ?? 'null')
    if (!saved?.from || !saved?.to || typeof saved.saved_at !== 'number') return null
    if (Date.now() - saved.saved_at > PERIOD_TTL_MS) {
      localStorage.removeItem(keyOf(page))
      return null
    }
    return saved
  } catch {
    return null
  }
}

/**
 * The period to reopen a page on, or `null` to use the page's default.
 *
 * @param {string} page As for {@link rememberPeriod}.
 * @param {{from?: string, to?: string}} [edge] The page's first and newest day NOW.
 * @returns {{from: string, to: string}|null}
 */
export function recallPeriod(page, edge = {}) {
  const saved = readEntry(page)
  if (!saved) return null
  const before = saved.edge ?? {}
  const wasOnLatest = Boolean(before.to) && saved.to === before.to
  if (!wasOnLatest || !edge.to || edge.to === before.to) return { from: saved.from, to: saved.to }

  // «Вся история» is extended, not slid: it is anchored at both ends, and
  // preserving its LENGTH would walk its start forward and quietly drop the
  // oldest days from the total.
  const wholeHistory = Boolean(before.from) && saved.from === before.from && Boolean(edge.from)
  const from = wholeHistory ? edge.from : shiftIso(edge.to, -daysBetween(saved.from, saved.to))
  rememberPeriod(page, from, edge.to, edge, saved.saved_at)
  return { from, to: edge.to }
}
