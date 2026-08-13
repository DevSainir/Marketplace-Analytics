import { formatPercent, formatSku } from '@/core/utils/format'

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

describe('formatSku', () => {
  it('uppercases a seller article however the seller typed it', () => {
    expect(formatSku('m-trx01-blk')).toBe('M-TRX01-BLK')
  })

  it('leaves an already-uppercase article alone', () => {
    expect(formatSku('M-TRX01-BLK')).toBe('M-TRX01-BLK')
  })

  it('leaves Russian bucket labels as prose', () => {
    // The P&L's sa_name column carries these next to the real articles.
    expect(formatSku('Без привязки к артикулу')).toBe('Без привязки к артикулу')
    expect(formatSku('Итого')).toBe('Итого')
  })

  it('leaves the nm fallback of an article-less card alone', () => {
    expect(formatSku('nm 940954338')).toBe('nm 940954338')
  })

  it('passes missing values straight through, so callers can still fall back', () => {
    expect(formatSku(null)).toBe(null)
    expect(formatSku('')).toBe('')
  })
})
