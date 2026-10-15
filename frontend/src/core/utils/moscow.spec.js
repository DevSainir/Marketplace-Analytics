import { formatMoscow, formatMoscowDate, moscowIsoDate } from '@/core/utils/moscow'

const STAMP = { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }

describe('formatMoscow', () => {
  it('prints the Moscow clock and says so', () => {
    // 07:47 UTC is 10:47 in Moscow, whatever zone the browser is in.
    expect(formatMoscow('2026-10-14T07:47:00Z', STAMP)).toBe('14 окт., 10:47 МСК')
  })

  it('leaves the label off when no time of day is shown', () => {
    expect(formatMoscow('2026-10-14T07:47:00Z', { day: 'numeric', month: 'long' })).toBe(
      '14 октября',
    )
  })

  it('dates an instant by the Moscow day it fell on', () => {
    // 22:30 UTC on the 13th is already 01:30 on the 14th in Moscow.
    expect(formatMoscowDate('2026-10-13T22:30:00Z')).toBe('14.10.2026')
  })

  it('prints the fallback for a missing or broken instant', () => {
    expect(formatMoscow(null, STAMP)).toBe('—')
    expect(formatMoscow('not a date', STAMP, '')).toBe('')
  })
})

describe('moscowIsoDate', () => {
  it('is the Moscow calendar day of the instant', () => {
    expect(moscowIsoDate('2026-10-13T20:59:00Z')).toBe('2026-10-13')
    expect(moscowIsoDate('2026-10-13T21:00:00Z')).toBe('2026-10-14')
  })

  it('is empty for something that is not an instant', () => {
    expect(moscowIsoDate('')).toBe('')
  })
})
