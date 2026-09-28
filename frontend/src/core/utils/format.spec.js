import { formatMoney, formatPercent, formatSku, moneyLabel } from '@/core/utils/format'

/** Intl groups thousands with a no-break space; the assertions read plain ones. */
const plain = (text) => text.replace(/\s/g, ' ')

describe('formatMoney', () => {
  it('states the figure in the currency the кабинет is settled in', () => {
    expect(plain(formatMoney(12345.6, 'KGS'))).toBe('12 346 KGS')
  })

  it('prints a bare number while the currency is unknown', () => {
    // A guessed unit misstates every figure by an exchange rate; none does not.
    expect(plain(formatMoney(12345.6))).toBe('12 346')
    expect(plain(formatMoney(12345.6, ''))).toBe('12 346')
  })

  it('keeps the decimals it is asked for', () => {
    // CPC is single units of money per click; rounding it to whole ones hides it.
    expect(formatMoney(10.26, 'KGS', 1)).toBe('10,3 KGS')
  })

  it('keeps zero as a figure and a missing value as an em dash', () => {
    expect(formatMoney(0, 'KGS')).toBe('0 KGS')
    expect(formatMoney(null, 'KGS')).toBe('—')
    expect(formatMoney(undefined)).toBe('—')
  })
})

describe('moneyLabel', () => {
  it("puts the кабинет's currency on a money heading", () => {
    expect(moneyLabel('Затраты', 'KGS')).toBe('Затраты, KGS')
  })

  it('leaves the heading bare while the currency is unknown', () => {
    expect(moneyLabel('Затраты', '')).toBe('Затраты')
    expect(moneyLabel('Затраты')).toBe('Затраты')
  })
})

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
