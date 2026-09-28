/**
 * Which currency a money metric is labelled with.
 *
 * One кабинет holds three: on «Демо» WB prices in RUB, advertises in KGS
 * since ~20.08 and settles in KGS. A price labelled with the settlement's
 * currency is the mistake this pins against.
 */
import { metricLabel, metricOf } from './metrics'

const currencies = { prices: 'RUB', ads: ['KGS'], settlement: 'KGS' }

describe('metricLabel', () => {
  it('labels a price with the currency WB states for prices', () => {
    expect(metricLabel(metricOf('seller_price'), currencies)).toBe('Цена до СПП, RUB')
  })

  it('labels the orders in money with the price currency too', () => {
    expect(metricLabel(metricOf('order_sum'), currencies)).toBe('Заказы, RUB')
  })

  it('labels advertising with the ad account currency', () => {
    expect(metricLabel(metricOf('cpc'), currencies)).toBe('CPC, KGS')
  })

  it('names both when the window crosses the account switching currency', () => {
    expect(metricLabel(metricOf('spend'), { ...currencies, ads: ['KGS', 'RUB'] })).toBe(
      'Расход на рекламу, KGS/RUB',
    )
  })

  it('labels the settlement figures with the settlement currency', () => {
    expect(metricLabel(metricOf('profit'), currencies)).toBe('Прибыль, KGS')
  })

  it('adds no unit to a count', () => {
    expect(metricLabel(metricOf('orders'), currencies)).toBe('Заказы, шт')
  })
})
