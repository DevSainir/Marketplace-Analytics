/**
 * «Сводка» says which of its figures mix currencies, and only when they do.
 *
 * «Демо» settles in KGS, prices in RUB, and advertised in RUB until
 * 20.08.2026 and in KGS since.
 */
import { currencyNotes } from '@/modules/summary/currencyNotes'

describe('currencyNotes', () => {
  it('warns that ДРР and margin mix roubles of ads with сомы of revenue before 20.08', () => {
    const [note] = currencyNotes({ settlement: 'KGS', prices: 'RUB', ads: ['RUB'] })

    expect(note).toContain('оплачена в рублях')
    expect(note).toContain('выручка — в сомах')
    expect(note).toContain('маржа')
  })

  it('does not warn about orders priced in roubles against ads in сомы', () => {
    // Taken down on 01.10.2026 at the owner's request; the mix remains
    // (CONVERSION-TODO in currencyNotes.js).
    expect(currencyNotes({ settlement: 'KGS', prices: 'RUB', ads: ['KGS'] })).toEqual([])
  })

  it('says nothing when every figure is in one currency', () => {
    expect(currencyNotes({ settlement: 'RUB', prices: 'RUB', ads: ['RUB'] })).toEqual([])
  })

  it('says nothing about a currency nobody stated', () => {
    expect(currencyNotes({ settlement: 'KGS', prices: '', ads: [''] })).toEqual([])
  })
})
