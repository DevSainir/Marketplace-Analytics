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

  it('warns that ДРР от заказов divides сомы of ads by orders valued in roubles after 20.08', () => {
    const notes = currencyNotes({ settlement: 'KGS', prices: 'RUB', ads: ['KGS'] })

    expect(notes).toHaveLength(1)
    expect(notes[0]).toContain('ДРР от заказов')
  })

  it('says both for a window across the switch', () => {
    expect(currencyNotes({ settlement: 'KGS', prices: 'RUB', ads: ['KGS', 'RUB'] })).toHaveLength(2)
  })

  it('says nothing when every figure is in one currency', () => {
    expect(currencyNotes({ settlement: 'RUB', prices: 'RUB', ads: ['RUB'] })).toEqual([])
  })

  it('says nothing about a currency nobody stated', () => {
    expect(currencyNotes({ settlement: 'KGS', prices: '', ads: [''] })).toEqual([])
  })
})
