import { formatPercent } from '@/core/utils/format'

describe('formatPercent', () => {
  it('formats a 0–100 value with the ru-RU locale and two fraction digits', () => {
    expect(formatPercent(12.3456)).toBe('12,35%')
  })

  it('pads whole numbers to two fraction digits', () => {
    expect(formatPercent(7)).toBe('7,00%')
  })

  it('keeps zero as a real value, not a dash', () => {
    expect(formatPercent(0)).toBe('0,00%')
  })

  it('renders an em dash for missing values', () => {
    expect(formatPercent(null)).toBe('—')
    expect(formatPercent(undefined)).toBe('—')
  })

  it('renders an em dash for non-finite numbers', () => {
    expect(formatPercent(NaN)).toBe('—')
    expect(formatPercent(Infinity)).toBe('—')
  })
})
