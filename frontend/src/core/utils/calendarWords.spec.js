import { formatDay, formatDayShort, weekdayOf } from '@/core/utils/calendarWords'

describe('formatDay', () => {
  it('writes the day first and the month as a word', () => {
    // "07/11" is a different day on each side of the Atlantic; "11 Jul" is not.
    expect(formatDay('2026-07-11')).toBe('11 Jul 2026')
  })

  it('abbreviates September to three letters like every other month', () => {
    expect(formatDay('2026-09-01')).toBe('1 Sep 2026')
  })

  it('prints a dash for no day', () => {
    expect(formatDay('')).toBe('—')
  })
})

describe('formatDayShort', () => {
  it('leaves the year to the page around it', () => {
    expect(formatDayShort('2026-10-22')).toBe('22 Oct')
  })
})

describe('weekdayOf', () => {
  it('names the weekday of the calendar day, not of the browser clock', () => {
    expect(weekdayOf('2026-07-19')).toBe('Sun')
    expect(weekdayOf('2026-07-20')).toBe('Mon')
  })
})
