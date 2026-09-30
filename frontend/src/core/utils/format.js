/** Shared ru-RU display formatters (single Intl instances, reused app-wide). */

const numberFormat = new Intl.NumberFormat('ru-RU')

/** 12345 -> "12 345" */
export function formatNumber(value) {
  return numberFormat.format(value)
}

const moneyFormats = new Map()

/** Signs of the currencies WB pays and prices our sellers in. */
const CURRENCY_SIGNS = { KGS: 'с', RUB: '₽' }

/**
 * The sign a figure carries in the currency it is in: «с» for the som, «₽» for
 * the rouble, the ISO code for anything else.
 *
 * Every figure carries its own sign — «57 600с», «4 120₽» — rather than a
 * heading saying «, KGS» over a column. A Kyrgyz кабинет holds money in two
 * currencies at once (settled in soms, priced in roubles, advertised in
 * whatever each campaign bills in), and a sign on the figure is the one place
 * a reader cannot miss it. A sum of both — spend across WB's 2026-08-20 move of
 * the ad account — carries both signs, because nothing here converts.
 *
 * @param {string|string[]} [currency] One ISO code, or the codes of a mixed sum.
 * @returns {string} The sign to append; `''` when the currency is unknown.
 */
export function currencySign(currency = '') {
  const codes = (Array.isArray(currency) ? currency : [currency]).filter(Boolean)
  return codes.map((code) => CURRENCY_SIGNS[code] ?? ` ${code}`).join('+')
}

/**
 * Money with the sign of the currency the source states, e.g. 12345.6 -> "12 346с".
 *
 * The ONE money formatter. There used to be two more pinned to RUB, and every
 * page built on them printed a rouble sign whatever the figure was in. The
 * currency is the FIGURE's, from the backend; this file only maps it to a sign.
 * Intl formatters are expensive to build, so one is memoised per precision.
 *
 * @param {number|string|null|undefined} value
 * @param {string|string[]} [currency] ISO code(s) from the data; falsy renders a bare number.
 * @param {number} [fractionDigits]
 * @returns {string} An em dash when the value is missing — a blank figure and a
 *   zero mean different things on a P&L.
 */
export function formatMoney(value, currency = '', fractionDigits = 0) {
  const figure = formatMoneyFigure(value, fractionDigits)
  return figure === '—' ? figure : figure + currencySign(currency)
}

/**
 * The number part of {@link formatMoney} alone, for a cell that sets the sign
 * in its own element (a narrow grid lets the sign give way before a digit).
 *
 * @param {number|string|null|undefined} value
 * @param {number} [fractionDigits]
 * @returns {string}
 */
export function formatMoneyFigure(value, fractionDigits = 0) {
  if (value === null || value === undefined || value === '') return '—'
  const amount = Number(value)
  if (!Number.isFinite(amount)) return '—'
  if (!moneyFormats.has(fractionDigits)) {
    moneyFormats.set(
      fractionDigits,
      new Intl.NumberFormat('ru-RU', {
        minimumFractionDigits: fractionDigits,
        maximumFractionDigits: fractionDigits,
      }),
    )
  }
  return moneyFormats.get(fractionDigits).format(amount)
}

/**
 * A money heading. Headings no longer carry the unit — every figure does
 * ({@link currencySign}) — so this returns the label as given. Kept for the
 * `labs` sandbox, which still imports it.
 *
 * @param {string} label The heading.
 * @returns {string}
 */
export function moneyLabel(label) {
  return label
}

/**
 * A seller article the way it is printed on the box — uppercase:
 * «m-trx01-blk» -> «M-TRX01-BLK». WB stores whatever casing the seller typed,
 * so the same article arrives lowercase in one report and uppercase in another
 * and the tables look inconsistent.
 *
 * The same fields also carry prose rather than a code: the P&L's «Без привязки
 * к артикулу» / «Итого» buckets, and the «nm 12345» fallback for a card with no
 * article at all. Neither is a SKU, so only pure-ASCII values that are not the
 * nm fallback are touched; everything else is returned as it came.
 *
 * @param {string|null|undefined} value
 * @returns {string|null|undefined} The input unchanged when it is not a code.
 */
export function formatSku(value) {
  if (!value) return value
  const text = String(value)
  if (text.startsWith('nm ') || !/^[ -~]+$/.test(text)) return text
  return text.toUpperCase()
}

const percentFormat = new Intl.NumberFormat('ru-RU', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

/**
 * 12.3456 -> "12,35%" (the value is already 0–100, not a 0–1 ratio).
 *
 * Non-finite input (null, undefined, NaN, ±Infinity) renders as an em dash
 * so a missing metric never crashes the view.
 */
export function formatPercent(value) {
  if (!Number.isFinite(value)) return '—'
  return `${percentFormat.format(value)}%`
}
