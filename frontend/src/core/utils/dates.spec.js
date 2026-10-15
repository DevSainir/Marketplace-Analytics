import { MAX_WINDOW_DAYS, daysBetween, isoDaysAgo, isoLocalDate } from '@/core/utils/dates'

describe('isoLocalDate', () => {
  it('formats using local date parts, not UTC', () => {
    // new Date(y, m, d, hh) is constructed in the local timezone; late-evening
    // local time must still format as the same local day.
    expect(isoLocalDate(new Date(2026, 6, 8, 23, 30))).toBe('2026-07-08')
    expect(isoLocalDate(new Date(2026, 0, 1, 0, 5))).toBe('2026-01-01')
  })

  it('zero-pads months and days', () => {
    expect(isoLocalDate(new Date(2026, 2, 5))).toBe('2026-03-05')
  })
})

describe('isoDaysAgo', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    // 20:30 UTC is 23:30 in Moscow — still the 8th there.
    vi.setSystemTime(new Date('2026-07-08T20:30:00Z'))
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('returns today for 0 and walks back across month boundaries', () => {
    expect(isoDaysAgo(0)).toBe('2026-07-08')
    expect(isoDaysAgo(6)).toBe('2026-07-02')
    expect(isoDaysAgo(8)).toBe('2026-06-30')
  })

  it('counts from the Moscow day, not the browser’s', () => {
    // 21:30 UTC: 00:30 on the 9th in Moscow, whatever the browser's zone says.
    vi.setSystemTime(new Date('2026-07-08T21:30:00Z'))
    expect(isoDaysAgo(0)).toBe('2026-07-09')
  })
})

describe('daysBetween', () => {
  it('counts whole days the way the API counts a window', () => {
    // The backend compares `(end - start).days` against its own ceiling, so
    // this has to be the same number — one off either way puts the page's note
    // and the API's refusal on different days.
    expect(daysBetween('2026-07-01', '2026-07-01')).toBe(0)
    expect(daysBetween('2026-07-01', '2026-07-08')).toBe(7)
  })

  it('is not thrown by a daylight-saving jump', () => {
    // Parsed as UTC on purpose: a local-time parse makes the clock-change month
    // 23 or 25 hours long, and the rounding then lands a day out.
    expect(daysBetween('2026-03-01', '2026-04-01')).toBe(31)
  })

  it('agrees with the ceiling the API enforces', () => {
    // A year is inside the bound; the day after it is not.
    expect(daysBetween('2025-09-19', '2026-09-19')).toBeLessThanOrEqual(MAX_WINDOW_DAYS)
    expect(daysBetween('2025-09-01', '2026-09-19')).toBeGreaterThan(MAX_WINDOW_DAYS)
  })
})
