import {
  currencySign,
  formatMoney,
  formatMoneyFigure,
  formatNumber,
  formatPercent,
  formatSku,
  normalizeTypedNumber,
  plural,
  withCurrency,
} from '@/core/utils/format'

describe('formatMoney', () => {
  it('puts the sign of its own currency in front of the figure', () => {
    // A KGS workspace is paid in soms and priced in roubles: the sign has to be
    // on the figure, not on a heading shared by both.
    expect(formatMoney(12345.6, 'KGS')).toBe('KGS 12,346')
    expect(formatMoney(4120, 'RUB')).toBe('₽4,120')
  })

  it('carries both signs on a sum of both currencies', () => {
    // Spend across WB's 2026-08-20 move of the ad account: nothing converts it.
    expect(formatMoney(900, ['KGS', 'RUB'])).toBe('KGS+₽900')
  })

  it('prints a bare number while the currency is unknown', () => {
    // A guessed unit misstates every figure by an exchange rate; none does not.
    expect(formatMoney(12345.6)).toBe('12,346')
    expect(formatMoney(12345.6, '')).toBe('12,346')
    expect(formatMoney(12345.6, [])).toBe('12,346')
  })

  it('keeps the decimals it is asked for', () => {
    // CPC is single units of money per click; rounding it to whole ones hides it.
    expect(formatMoney(10.26, 'KGS', 1)).toBe('KGS 10.3')
  })

  it('puts the minus before the sign', () => {
    expect(formatMoney(-350, 'RUB')).toBe('-₽350')
    expect(formatMoney(-350, 'KGS')).toBe('-KGS 350')
  })

  it('keeps zero as a figure and a missing value as an em dash, with no sign', () => {
    expect(formatMoney(0, 'KGS')).toBe('KGS 0')
    expect(formatMoney(null, 'KGS')).toBe('—')
    expect(formatMoney(undefined)).toBe('—')
  })
})

describe('currencySign', () => {
  it('names an unfamiliar currency by its code rather than dropping it', () => {
    expect(currencySign('KZT')).toBe('KZT')
  })
})

describe('withCurrency', () => {
  it('sets a code off by a space and a symbol not at all', () => {
    expect(withCurrency('1,200', 'KZT')).toBe('KZT 1,200')
    expect(withCurrency('1,200', 'RUB')).toBe('₽1,200')
  })

  it('leaves a missing figure without a sign', () => {
    expect(withCurrency('—', 'RUB')).toBe('—')
  })
})

describe('formatMoneyFigure', () => {
  it('is the figure of formatMoney without the sign', () => {
    expect(formatMoneyFigure(12345.6)).toBe('12,346')
  })
})

describe('formatPercent', () => {
  it('formats a 0–100 value with a decimal point and two fraction digits', () => {
    expect(formatPercent(12.3456)).toBe('12.35%')
  })

  it('pads whole numbers to two fraction digits', () => {
    expect(formatPercent(7)).toBe('7.00%')
  })

  it('keeps zero as a real value, not a dash', () => {
    expect(formatPercent(0)).toBe('0.00%')
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

  it('leaves a label with spaces in it as prose', () => {
    // A group or bucket name can sit in the same column as the real articles.
    expect(formatSku('Not tied to a SKU')).toBe('Not tied to a SKU')
  })

  it('leaves an article in another alphabet as the seller wrote it', () => {
    expect(formatSku('\u03b1\u03b2-01')).toBe('\u03b1\u03b2-01')
  })

  it('leaves the nm fallback of an article-less card alone', () => {
    expect(formatSku('nm 940954338')).toBe('nm 940954338')
  })

  it('passes missing values straight through, so callers can still fall back', () => {
    expect(formatSku(null)).toBe(null)
    expect(formatSku('')).toBe('')
  })
})

describe('formatNumber', () => {
  it('prints a real zero as a zero', () => {
    expect(formatNumber(0)).toBe('0')
  })

  it('groups thousands with commas', () => {
    expect(formatNumber(1091260)).toBe('1,091,260')
  })

  it('prints a missing figure as a dash, never as a zero', () => {
    // "WB has not told us" and "there were none" are different answers; the
    // copies this replaced turned every null into "0".
    expect(formatNumber(null)).toBe('—')
    expect(formatNumber(undefined)).toBe('—')
  })
})

describe('plural', () => {
  const forms = ['reason', 'reasons']

  it.each([
    [1, 'reason'],
    [-1, 'reason'],
    [0, 'reasons'],
    [2, 'reasons'],
    [21, 'reasons'],
  ])('%i → %s', (n, word) => {
    expect(plural(n, forms)).toBe(word)
  })
})

describe('normalizeTypedNumber', () => {
  it.each([
    ['1,200', '1200'],
    ['1 200', '1200'],
    ['1,200.50', '1200.50'],
    ['12,345,678', '12345678'],
    ['795,50', '795.50'],
    ['1,5', '1.5'],
    ['', ''],
  ])('%s → %s', (typed, normal) => {
    // "1,200" is twelve hundred in English, "795,50" a price with kopecks in
    // the way sellers on WB write one; reading either the other way round
    // stores a cost a thousand times off.
    expect(normalizeTypedNumber(typed)).toBe(normal)
  })
})
