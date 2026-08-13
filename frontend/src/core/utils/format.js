/** Shared ru-RU display formatters (single Intl instances, reused app-wide). */

const numberFormat = new Intl.NumberFormat('ru-RU')

const currencyFormat = new Intl.NumberFormat('ru-RU', {
  style: 'currency',
  currency: 'RUB',
  maximumFractionDigits: 0,
})

/** 12345 -> "12 345" */
export function formatNumber(value) {
  return numberFormat.format(value)
}

/** 12345.6 -> "12 346 ₽" */
export function formatCurrency(value) {
  return currencyFormat.format(value)
}

const moneyFormats = new Map()

/**
 * Money in whatever currency the source states, e.g. 12345.6 -> "12 346 KGS".
 *
 * Separate from `formatCurrency`, which is pinned to RUB: the WB settlement
 * reports of a Kyrgyz account are denominated in KGS, and rendering those as ₽
 * would misstate every figure on a financial statement by an exchange rate.
 * Intl formatters are expensive to build, so one is memoised per currency.
 *
 * @param {number|string|null|undefined} value
 * @param {string} [currency] ISO code from the data; falsy renders a bare number.
 * @param {number} [fractionDigits]
 * @returns {string} An em dash when the value is missing — a blank figure and a
 *   zero mean different things on a P&L.
 */
export function formatMoney(value, currency = '', fractionDigits = 0) {
  if (value === null || value === undefined || value === '') return '—'
  const amount = Number(value)
  if (!Number.isFinite(amount)) return '—'
  const key = `${currency}|${fractionDigits}`
  if (!moneyFormats.has(key)) {
    moneyFormats.set(
      key,
      new Intl.NumberFormat('ru-RU', {
        minimumFractionDigits: fractionDigits,
        maximumFractionDigits: fractionDigits,
      }),
    )
  }
  const formatted = moneyFormats.get(key).format(amount)
  return currency ? `${formatted} ${currency}` : formatted
}

const currencyTenthsFormat = new Intl.NumberFormat('ru-RU', {
  style: 'currency',
  currency: 'RUB',
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
})

/** 10.26 -> "10,3 ₽" — one decimal for small per-click money (CPC). */
export function formatCurrencyTenths(value) {
  return currencyTenthsFormat.format(value)
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
