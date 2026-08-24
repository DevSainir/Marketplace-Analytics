/**
 * Calendar constants and the month-grid builder for the period picker.
 *
 * Split out of `PeriodSelector` because none of it is about picking a period:
 * it is the Russian month/weekday vocabulary and the arithmetic that turns a
 * (year, month) pair into the 6x7 grid a month is drawn on — Monday-first,
 * with the leading and trailing days of the neighbouring months filled in so
 * every month renders the same shape.
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
]

/**
 * The rolling window one preset stands for.
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
  const to = end || isoDaysAgo(0)
  const last = new Date(`${to}T00:00:00`)
  return { from: isoLocalDate(new Date(last.getTime() - (days - 1) * 86400000)), to }
}

/**
 * "Today" as the calendar sees it.
 *
 * Module-level, so it is fixed at import: every consumer must agree on which
 * day is today, and a picker that disagreed with its own disabled-day rule
 * between two renders would let a user select a future day.
 */
export const TODAY = new Date()
export const TODAY_ISO = isoLocalDate(TODAY)

export function buildMonth(year, month) {
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
      disabled: iso > TODAY_ISO,
    })
  }
  return cells
}

/**
 * The two-month view the picker scrolls through, and the arrows that move it.
 *
 * Two months side by side rather than one: a range usually spans a month
 * boundary, and paging back and forth to pick its two ends is the single most
 * annoying thing a date-range picker can do.
 *
 * @param {import('vue').Ref<number>} viewYear
 * @param {import('vue').Ref<number>} viewMonth 0-based, the LEFT month of the pair.
 */
export function useCalendarView(viewYear, viewMonth) {
  const monthsToShow = computed(() =>
    [0, 1].map((offset) => {
      const d = new Date(viewYear.value, viewMonth.value + offset, 1)
      return {
        label: `${MONTHS[d.getMonth()]} ${d.getFullYear()}`,
        cells: buildMonth(d.getFullYear(), d.getMonth()),
      }
    }),
  )

  // The right month may reach the current month, never beyond (no future-only view).
  const canGoNext = computed(
    () =>
      new Date(viewYear.value, viewMonth.value + 1, 1) <
      new Date(TODAY.getFullYear(), TODAY.getMonth(), 1),
  )

  function shiftView(delta) {
    const d = new Date(viewYear.value, viewMonth.value + delta, 1)
    viewYear.value = d.getFullYear()
    viewMonth.value = d.getMonth()
  }

  return { monthsToShow, canGoNext, shiftView }
}
