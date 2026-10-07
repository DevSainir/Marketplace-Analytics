/**
 * The calendar's bounds and presets, as every page sees them.
 *
 * Pages only state their bounds — first day with data, last pickable day,
 * longest window — and the preset windows, the one lit preset and the greyed
 * days all follow from these functions. A page computing any of it on its own
 * is how highlighting broke twice, and how the summary came to light two
 * presets at once.
 */
import {
  activePreset,
  buildMonth,
  pickableSpan,
  presetWindow,
  presetsFor,
} from '@/core/utils/calendarModel'

describe('presetsFor', () => {
  it('offers «Вся история» when the page knows where its data starts', () => {
    expect(presetsFor('2024-01-29').map((p) => p.label)).toEqual([
      '7 дней',
      '30 дней',
      '90 дней',
      'Вся история',
    ])
  })

  it('offers «180 дней» when it does not', () => {
    expect(presetsFor('').map((p) => p.label)).toEqual(['7 дней', '30 дней', '90 дней', '180 дней'])
  })
})

describe('presetWindow', () => {
  it('counts the end day as one of the N', () => {
    expect(presetWindow(7, { end: '2026-03-10' })).toEqual({ from: '2026-03-04', to: '2026-03-10' })
  })

  it('never starts before the first day the page has data for', () => {
    // «90 дней» on a кабинет a month old is that month, not a window reaching
    // into days the calendar greys out.
    const window = presetWindow(90, { end: '2026-10-04', historyFrom: '2026-09-05' })

    expect(window).toEqual({ from: '2026-09-05', to: '2026-10-04' })
  })

  it('never runs longer than the page answers for', () => {
    const window = presetWindow(0, { end: '2026-10-04', historyFrom: '2020-01-01', maxDays: 367 })

    expect(window).toEqual({ from: '2025-10-03', to: '2026-10-04' })
  })
})

describe('activePreset', () => {
  it('marks only «Вся история» when another preset produces the same dates', () => {
    // History exactly thirty days long: «30 дней» and «Вся история» are one
    // window. Both lit read as two choices made at once.
    const bounds = { end: '2026-10-04', historyFrom: '2026-09-05' }

    expect(activePreset('2026-09-05', '2026-10-04', bounds)).toBe(0)
  })

  it('marks the rolling preset that set the window', () => {
    const bounds = { end: '2026-10-04', historyFrom: '2024-01-29' }

    expect(activePreset('2026-09-05', '2026-10-04', bounds)).toBe(30)
  })

  it('marks nothing for a hand-picked window', () => {
    expect(activePreset('2026-09-06', '2026-10-04', { end: '2026-10-04' })).toBeNull()
  })
})

describe('pickableSpan', () => {
  it("bounds the days by the page's first and last day", () => {
    expect(pickableSpan({ min: '2024-01-29', max: '2026-10-04' })).toEqual({
      lo: '2024-01-29',
      hi: '2026-10-04',
    })
  })

  it('narrows to the longest window around the first click', () => {
    // 367 days counted with both ends: the second click can land 366 days
    // either side of the first, and not a day further.
    const span = pickableSpan({ max: '2026-10-04', anchor: '2026-01-01', maxDays: 367 })

    expect(span).toEqual({ lo: '2024-12-31', hi: '2026-10-04' })
  })
})

describe('buildMonth', () => {
  it('disables the days outside the pickable span', () => {
    const cells = buildMonth(2026, 8, { lo: '2026-09-10', hi: '2026-09-20' })
    const enabled = cells.filter((cell) => !cell.disabled).map((cell) => cell.iso)

    expect(enabled[0]).toBe('2026-09-10')
    expect(enabled.at(-1)).toBe('2026-09-20')
    expect(enabled).toHaveLength(11)
  })
})
