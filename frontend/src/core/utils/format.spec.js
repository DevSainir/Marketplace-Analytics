import {
  currencySign,
  formatMoney,
  formatMoneyFigure,
  formatNumber,
  formatPercent,
  formatSku,
  plural,
} from '@/core/utils/format'

/** Intl groups thousands with a no-break space; the assertions read plain ones. */
const plain = (text) => text.replace(/\s/g, ' ')

describe('formatMoney', () => {
  it('puts the sign of its own currency on the figure', () => {
    // A KGS workspace is paid in soms and priced in roubles: the sign has to be
    // on the figure, not on a heading shared by both.
    expect(plain(formatMoney(12345.6, 'KGS'))).toBe('12 346с')
    expect(plain(formatMoney(4120, 'RUB'))).toBe('4 120₽')
  })

  it('carries both signs on a sum of both currencies', () => {
    // Spend across WB's 2026-08-20 move of the ad account: nothing converts it.
    expect(plain(formatMoney(900, ['KGS', 'RUB']))).toBe('900с+₽')
  })

  it('prints a bare number while the currency is unknown', () => {
    // A guessed unit misstates every figure by an exchange rate; none does not.
    expect(plain(formatMoney(12345.6))).toBe('12 346')
    expect(plain(formatMoney(12345.6, ''))).toBe('12 346')
    expect(plain(formatMoney(12345.6, []))).toBe('12 346')
  })

  it('keeps the decimals it is asked for', () => {
    // CPC is single units of money per click; rounding it to whole ones hides it.
    expect(formatMoney(10.26, 'KGS', 1)).toBe('10,3с')
  })

  it('keeps zero as a figure and a missing value as an em dash, with no sign', () => {
    expect(formatMoney(0, 'KGS')).toBe('0с')
    expect(formatMoney(null, 'KGS')).toBe('—')
    expect(formatMoney(undefined)).toBe('—')
  })
})

describe('currencySign', () => {
  it('names an unfamiliar currency by its code rather than dropping it', () => {
    expect(currencySign('KZT')).toBe(' KZT')
  })
})

describe('formatMoneyFigure', () => {
  it('is the figure of formatMoney without the sign', () => {
    expect(plain(formatMoneyFigure(12345.6))).toBe('12 346')
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

describe('formatNumber', () => {
  it('prints a real zero as a zero', () => {
    expect(formatNumber(0)).toBe('0')
  })

  it('prints a missing figure as a dash, never as a zero', () => {
    // «WB has not told us» and «there were none» are different answers; the
    // copies this replaced turned every null into «0».
    expect(formatNumber(null)).toBe('—')
    expect(formatNumber(undefined)).toBe('—')
  })
})

describe('plural', () => {
  const forms = ['причина', 'причины', 'причин']

  it.each([
    [1, 'причина'],
    [2, 'причины'],
    [5, 'причин'],
    [11, 'причин'],
    [12, 'причин'],
    [21, 'причина'],
    [24, 'причины'],
    [111, 'причин'],
  ])('%i → %s', (n, word) => {
    expect(plural(n, forms)).toBe(word)
  })
})
