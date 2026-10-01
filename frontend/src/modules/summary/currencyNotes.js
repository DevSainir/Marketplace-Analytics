/**
 * What the «Сводка» figures mix, said in words rather than hidden.
 *
 * A кабинет that settles in KGS holds three kinds of money: revenue, margin and
 * fines in the settlement's currency, the orders' volume at the prices (RUB on
 * «Демо»), and advertising in what each campaign bills in — RUB before
 * 20.08.2026, KGS after. The page converts nothing, so a ДРР or a margin built
 * over two of them is off by the exchange rate. Each note names the figures
 * that are, and only when the window actually holds the mix.
 *
 * CONVERSION-TODO: once the service converts at the Bank of Russia rate these
 * notes go, and the figures they warn about become exact.
 */
import { currencyInWords } from '@/core/utils/format'

/** «в рублях», «в рублях и в сомах» — the currencies of a list, in words. */
function inWords(codes) {
  return codes.map(currencyInWords).join(' и ')
}

/**
 * @param {{settlement?: string, ads?: string[]}} currencies
 *   The response's `currency` and `ad_currencies`.
 * @returns {string[]} The notes to print under the cards; empty when nothing mixes.
 */
export function currencyNotes({ settlement = '', ads = [] } = {}) {
  const stated = ads.filter(Boolean)
  const notes = []
  const offSettlement = stated.filter((code) => code !== settlement)
  if (settlement && offSettlement.length) {
    notes.push(
      `Часть рекламы за период оплачена ${inWords(offSettlement)}, а выручка — ` +
        `${currencyInWords(settlement)}. Средний ДРР, ДРР от продаж и маржа ` +
        'считаются без пересчёта курса.',
    )
  }
  // The second note — orders valued at RUB prices against ads in сомы, so
  // «ДРР от заказов» is off by the rate — was taken down on 01.10.2026 at the
  // owner's request: it showed on every window since 20.08 and read as noise.
  // The mix is still there. CONVERSION-TODO: it goes away with conversion.
  return notes
}
