/**
 * The calendar's vocabulary and arithmetic, shared by every date picker.
 *
 * Split out of `PeriodSelector` because none of it is about a popover: the
 * Russian month/weekday names, the 6x7 grid a month is drawn on, the windows
 * the quick presets stand for and the days a page lets the user click. Pages
 * only state their bounds — first day, last day, longest window — and both
 * the presets and the greyed-out days follow from them, so no page keeps its
 * own copy of this arithmetic. Two copies of it is how preset highlighting
 * broke twice.
 */

import { computed } from 'vue'

import { isoDaysAgo, isoLocalDate } from '@/core/utils/dates'

/** Monday-first, matching the grid the picker draws. */
export const WEEKDAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']

export const MONTHS = [
  'Январь',
  'Февраль',
  'Март',
  'Апрель',
  'Май',
  'Июнь',
  'Июль',
  'Август',
  'Сентябрь',
  'Октябрь',
  'Ноябрь',
  'Декабрь',
]
export const PRESETS = [
  { label: '7 дней', days: 7 },
  { label: '30 дней', days: 30 },
  { label: '90 дней', days: 90 },
  { label: '180 дней', days: 180 },
]

/**
 * The footer's presets for a picker: 7/30/90 and a fourth that depends on
 * whether the page knows where its data begins — «Вся история» from that day
 * when it does, «180 дней» when it does not. «Вся история» carries `days: 0`;
 * {@link presetWindow} resolves it.
 *
 * @param {string} [historyFrom] The page's first day, ISO; empty = stock presets.
 */
export function presetsFor(historyFrom = '') {
  return historyFrom ? [...PRESETS.slice(0, -1), { label: 'Вся история', days: 0 }] : PRESETS
}

/**
 * Move an ISO day along the local calendar.
 *
 * By calendar day rather than by 86 400 000 ms, so a daylight-saving change in
 * the browser's zone cannot land the result on the wrong date.
 *
 * @param {string} iso Day to move, `YYYY-MM-DD`.
 * @param {number} days Offset; negative moves back.
 */
export function shiftIso(iso, days) {
  const date = new Date(`${iso}T00:00:00`)
  date.setDate(date.getDate() + days)
  return isoLocalDate(date)
}

/** "2026-07-11" → "11.07.2026": how every date picker in the app writes a day. */
export function formatDay(iso) {
  if (!iso) return '—'
  const [y, m, d] = iso.split('-')
  return `${d}.${m}.${y}`
}

/**
 * The window a preset of {@link presetsFor} applies.
 *
 * A rolling window ending on `end`, or for «Вся история» everything from
 * `historyFrom`. Either is then held inside the page's own bounds: it never
 * starts before the first day the page has data for, and never runs longer
 * than `maxDays` — «90 дней» on a кабинет a month old is that month, not a
 * window the calendar would refuse to draw.
 *
 * @param {number} days The preset's length; 0 = «Вся история».
 * @param {{end?: string, historyFrom?: string, maxDays?: number}} [bounds]
 *   `end` — last day, ISO, empty = today; `historyFrom` — first day with data;
 *   `maxDays` — longest window the page answers for, both ends counted, 0 = none.
 * @returns {{from: string, to: string}} An inclusive ISO range.
 */
export function presetWindow(days, { end = '', historyFrom = '', maxDays = 0 } = {}) {
  const to = end || isoDaysAgo(0)
  let from = days ? shiftIso(to, -(days - 1)) : historyFrom
  if (historyFrom && historyFrom <= to && from < historyFrom) from = historyFrom
  if (maxDays && from && from < shiftIso(to, -(maxDays - 1))) from = shiftIso(to, -(maxDays - 1))
  return { from, to }
}

/**
 * Which preset, if any, stands for the window on screen — at most ONE.
 *
 * Two presets can produce the same window once it is held inside the page's
 * bounds: on a кабинет with exactly thirty days of history «30 дней» and «Вся
 * история» are the same dates. Marking both read as two choices made at once,
 * so «Вся история» wins such a tie and otherwise the shortest match does.
 *
 * @param {string} from Window on screen, ISO.
 * @param {string} to Window on screen, ISO.
 * @param {{end?: string, historyFrom?: string, maxDays?: number}} [bounds] As for {@link presetWindow}.
 * @returns {number|null} The preset's `days` (0 = «Вся история»), or `null` for a hand-picked window.
 */
export function activePreset(from, to, bounds = {}) {
  const matches = presetsFor(bounds.historyFrom).filter((preset) => {
    const window = presetWindow(preset.days, bounds)
    return Boolean(window.from) && window.from === from && window.to === to
  })
  if (!matches.length) return null
  return (matches.find((preset) => preset.days === 0) ?? matches[0]).days
}

/**
 * The rolling window one preset stands for, with no bounds applied.
 *
 * `end` is the day it finishes on — today for live traffic data, or the
 * caller's newest SETTLED day for the P&L, where «7 дней» ending today would
 * include days no WB report covers yet and read as a collapse in sales.
 *
 * The end day COUNTS as one of the N: «7 дней» to the 10th is the 4th to the
 * 10th. Off by one here is a whole day appearing or vanishing, which is why it
 * lives beside `PRESETS` rather than inside a component.
 *
 * @param {number} days Length of the window.
 * @param {string} [end] Last day, ISO. Empty = today.
 * @returns {{from: string, to: string}} An inclusive ISO range.
 */
export function presetRange(days, end = '') {
  return presetWindow(days, { end })
}

/**
 * "Today" as the calendar sees it — the Moscow day, like the rest of the service.
 *
 * Module-level, so it is fixed at import: every consumer must agree on which
 * day is today, and a picker that disagreed with its own disabled-day rule
 * between two renders would let a user select a future day.
 */
export const TODAY_ISO = isoDaysAgo(0)
/** The same Moscow day as a local-midnight Date, for the month grid. */
export const TODAY = new Date(`${TODAY_ISO}T00:00:00`)

/**
 * The days a picker lets the user click, as an inclusive `{lo, hi}` pair.
 *
 * Everything a page knows about its own data becomes a greyed-out day rather
 * than an error after the fact: nothing before the first day it holds (`min`),
 * nothing after the last (`max`, today by default), and — while the second end
 * of a range is being chosen — nothing further from the first click than the
 * longest window the page answers for (`maxDays`, both ends counted).
 *
 * @param {{min?: string, max?: string, anchor?: string|null, maxDays?: number}} [bounds]
 * @returns {{lo: string, hi: string}} `lo` is empty when there is no floor.
 */
export function pickableSpan({ min = '', max = '', anchor = null, maxDays = 0 } = {}) {
  let lo = min
  let hi = max || TODAY_ISO
  if (anchor && maxDays) {
    const earliest = shiftIso(anchor, -(maxDays - 1))
    const latest = shiftIso(anchor, maxDays - 1)
    if (!lo || earliest > lo) lo = earliest
    if (latest < hi) hi = latest
  }
  return { lo, hi }
}

/**
 * A 6×7 grid of day cells for one month, Monday-first, with the neighbouring
 * months' leading and trailing days filled in.
 *
 * @param {number} year
 * @param {number} month 0-based.
 * @param {{lo: string, hi: string}} [span] Pickable days ({@link pickableSpan}); the rest are disabled.
 */
export function buildMonth(year, month, span = { lo: '', hi: TODAY_ISO }) {
  const firstWeekday = (new Date(year, month, 1).getDay() + 6) % 7 // Mon = 0
  const start = new Date(year, month, 1 - firstWeekday)
  const cells = []
  for (let i = 0; i < 42; i += 1) {
    const d = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i)
    const iso = isoLocalDate(d)
    cells.push({
      iso,
      day: d.getDate(),
      inMonth: d.getMonth() === month,
      disabled: iso > span.hi || (Boolean(span.lo) && iso < span.lo),
    })
  }
  return cells
}

/** First of the month an ISO day falls in, as a Date. */
function monthStart(iso) {
  const [y, m] = iso.split('-').map(Number)
  return new Date(y, m - 1, 1)
}

/**
 * The months a picker shows, and the arrows that move them.
 *
 * Two side by side where there is room for them, because a range usually spans
 * a month boundary and paging back and forth to pick its two ends is the
 * single most annoying thing a date-range picker can do; one on a narrow
 * screen, where two would not fit beside each other. The arrows stop at the
 * months holding the first and last pickable day.
 *
 * @param {import('vue').Ref<number>} viewYear
 * @param {import('vue').Ref<number>} viewMonth 0-based, the FIRST month shown.
 * @param {{count?: () => number, span?: () => {lo: string, hi: string}}} [options]
 *   Getters, so the view follows a change of either.
 */
export function useCalendarView(viewYear, viewMonth, options = {}) {
  const count = options.count ?? (() => 2)
  const span = options.span ?? (() => ({ lo: '', hi: TODAY_ISO }))

  const monthsToShow = computed(() =>
    Array.from({ length: count() }, (_, offset) => {
      const d = new Date(viewYear.value, viewMonth.value + offset, 1)
      return {
        label: `${MONTHS[d.getMonth()]} ${d.getFullYear()}`,
        cells: buildMonth(d.getFullYear(), d.getMonth(), span()),
      }
    }),
  )

  const canGoNext = computed(
    () => new Date(viewYear.value, viewMonth.value + count() - 1, 1) < monthStart(span().hi),
  )
  const canGoPrev = computed(
    () => !span().lo || new Date(viewYear.value, viewMonth.value, 1) > monthStart(span().lo),
  )

  /** Point the view so `iso`'s month is the LAST one shown. */
  function showEndingAt(iso) {
    const d = monthStart(iso || TODAY_ISO)
    d.setMonth(d.getMonth() - (count() - 1))
    viewYear.value = d.getFullYear()
    viewMonth.value = d.getMonth()
  }

  function shiftView(delta) {
    const d = new Date(viewYear.value, viewMonth.value + delta, 1)
    viewYear.value = d.getFullYear()
    viewMonth.value = d.getMonth()
  }

  return { monthsToShow, canGoNext, canGoPrev, shiftView, showEndingAt }
}
