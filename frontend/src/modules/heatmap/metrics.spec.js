/**
 * Which currency sign a money figure carries.
 *
 * One workspace holds three: WB prices it in RUB, advertises in KGS
 * since 20.08.2026 and settles in KGS. A price signed with the settlement's
 * currency is the mistake this pins against.
 */
import { cellText, currencyOf, formatValue, metricLabel, metricOf } from './metrics'

const currencies = { prices: 'RUB', orders: 'KGS', ads: ['KGS'], settlement: 'KGS' }

/** Intl groups thousands with a no-break space; the assertions read plain ones. */
const plain = (text) => text.replace(/\s/g, ' ')

const printed = (key, value, grid = currencies) => {
  const metric = metricOf(key)
  return plain(formatValue(value, metric.unit, currencyOf(metric, grid)))
}

describe('a money figure carries its own currency sign', () => {
  it('signs a price with the currency WB states for prices', () => {
    expect(printed('seller_price', 4120)).toBe('4 120₽')
  })

  it("signs the orders in money with WB's funnel sums' currency, not the prices'", () => {
    expect(printed('order_sum', 8240)).toBe('8 240с')
  })

  it('signs advertising with the ad account currency', () => {
    expect(printed('cpc', 23)).toBe('23с')
  })

  it('carries both signs when the window crosses the account switching currency', () => {
    expect(printed('spend', 900, { ...currencies, ads: ['KGS', 'RUB'] })).toBe('900с+₽')
  })

  it('signs the settlement figures with the settlement currency', () => {
    expect(printed('profit', 1240)).toBe('1 240с')
  })

  it('adds no sign to a count', () => {
    expect(printed('orders', 12)).toBe('12')
  })
})

describe('metricLabel', () => {
  it('names a money metric without a currency — the sign is on the figure', () => {
    expect(metricLabel(metricOf('spend'))).toBe('Расход на рекламу')
  })
})

describe('cellText', () => {
  const spend = metricOf('spend')

  it('signs a spend cell with its own campaigns currency, column by column', () => {
    const row = { total: null, values: [900, 800], units: ['RUB', 'KGS'], total_unit: '' }

    expect(plain(cellText(row, 0, spend, currencies))).toBe('900₽')
    expect(plain(cellText(row, 1, spend, currencies))).toBe('800с')
    expect(cellText(row, 'total', spend, currencies)).toBe('—')
  })

  it("falls back to the grid's currency for a metric with no per-cell units", () => {
    const row = { total: 12, values: [12] }

    expect(plain(cellText(row, 0, metricOf('order_sum'), currencies))).toBe('12с')
  })
})
