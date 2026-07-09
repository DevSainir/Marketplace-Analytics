import { isoDaysAgo, isoLocalDate } from '@/core/utils/dates'

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
    vi.setSystemTime(new Date(2026, 6, 8, 23, 30))
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('returns today for 0 and walks back across month boundaries', () => {
    expect(isoDaysAgo(0)).toBe('2026-07-08')
    expect(isoDaysAgo(6)).toBe('2026-07-02')
    expect(isoDaysAgo(8)).toBe('2026-06-30')
  })
})
