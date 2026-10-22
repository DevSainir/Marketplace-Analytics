/**
 * Shared en-US display formatters (single Intl instances, reused app-wide).
 *
 * One rule runs through all of them: an em dash means "no figure" and a zero
 * means "the figure is zero". They are different answers — "WB has not told
 * us" against "there were none" — so a missing value is never printed as 0 and
 * a real zero is never hidden behind a dash. Pages used to write their own
 * copies (`Number(v ?? 0).toLocaleString()` five times over), and each copy
 * turned "unknown" into "0".
 */

const numberFormat = new Intl.NumberFormat('en-US')

/** A figure as a number, or `null` when there is none (null, '', NaN, ±Infinity). */
function figureOf(value) {
  if (value === null || value === undefined || value === '') return null
  const amount = Number(value)
  return Number.isFinite(amount) ? amount : null
}

/** 12345 -> "12,345"; a missing value -> "—". */
export function formatNumber(value) {
  const amount = figureOf(value)
  return amount === null ? '—' : numberFormat.format(amount)
}

const moneyFormats = new Map()

/** Signs of the currencies WB pays and prices our sellers in. */
const CURRENCY_SIGNS = { RUB: '₽' }

/**
 * The sign of a figure's currency: «₽» for the rouble, the ISO code for
 * anything else — the som included, whose own sign is a letter of the Russian
 * alphabet and would read as a typo here.
 *
 * Every figure carries its own sign — "KGS 57,600", "₽4,120" — rather than a
 * heading saying ", KGS" over a column. A Kyrgyz workspace holds money in two
 * currencies at once (settled in soms, priced in roubles, advertised in
 * whatever each campaign bills in), and a sign on the figure is the one place
 * a reader cannot miss it. A sum of both — spend across WB's 2026-08-20 move of
 * the ad account — carries both signs, because nothing here converts.
 *
 * @param {string|string[]} [currency] One ISO code, or the codes of a mixed sum.
 * @returns {string} The sign; `''` when the currency is unknown.
 */
export function currencySign(currency = '') {
  const codes = (Array.isArray(currency) ? currency : [currency]).filter(Boolean)
  return codes.map((code) => CURRENCY_SIGNS[code] ?? code).join('+')
}

/**
 * A figure with its currency in front, the way English writes money: "₽4,120",
 * "KGS 57,600", "-₽350". A code is set off by a space and a symbol is not; a
 * minus goes before either.
 *
 * @param {string} figure An already formatted number, or "—".
 * @param {string|string[]} [currency] ISO code(s); falsy leaves the figure bare.
 * @returns {string}
 */
export function withCurrency(figure, currency = '') {
  const sign = currencySign(currency)
  if (!sign || figure === '—') return figure
  const negative = figure.startsWith('-')
  const digits = negative ? figure.slice(1) : figure
  const gap = /[A-Z]$/.test(sign) ? ' ' : ''
  return `${negative ? '-' : ''}${sign}${gap}${digits}`
}

/** How a sentence names a currency: "in soms", "in rubles". */
const CURRENCY_IN_WORDS = { KGS: 'in soms', RUB: 'in rubles' }

/**
 * A currency as running text says it — "Cost price … in soms" rather than
 * "in KGS". An unfamiliar code is kept as the code.
 *
 * @param {string} [currency] ISO code.
 * @returns {string} `''` when the currency is unknown.
 */
export function currencyInWords(currency = '') {
  if (!currency) return ''
  return CURRENCY_IN_WORDS[currency] ?? `in ${currency}`
}

/**
 * Money with the sign of the currency the source states, e.g. 12345.6 -> "KGS 12,346".
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
  return withCurrency(formatMoneyFigure(value, fractionDigits), currency)
}

/**
 * The number part of {@link formatMoney} alone, for a cell that sets the sign
 * in its own element (a narrow grid lets the sign give way before a digit) —
 * in front of the figure, as {@link withCurrency} places it.
 *
 * @param {number|string|null|undefined} value
 * @param {number} [fractionDigits]
 * @returns {string}
 */
export function formatMoneyFigure(value, fractionDigits = 0) {
  const amount = figureOf(value)
  if (amount === null) return '—'
  if (!moneyFormats.has(fractionDigits)) {
    moneyFormats.set(
      fractionDigits,
      new Intl.NumberFormat('en-US', {
        minimumFractionDigits: fractionDigits,
        maximumFractionDigits: fractionDigits,
      }),
    )
  }
  return moneyFormats.get(fractionDigits).format(amount)
}

/**
 * A seller article the way it is printed on the box — uppercase:
 * "m-trx01-blk" -> "M-TRX01-BLK". WB stores whatever casing the seller typed,
 * so the same article arrives lowercase in one report and uppercase in another
 * and the tables look inconsistent.
 *
 * Only a code is touched: one printable-ASCII token with no space in it. The
 * "nm 12345" fallback for a card with no article, a group or bucket name, and
 * an article written in another alphabet are returned as they came. A one-word
 * label that is not an article — a P&L "Total" row — is the caller's to keep
 * away from here, because nothing in the text tells it from a code.
 *
 * @param {string|null|undefined} value
 * @returns {string|null|undefined} The input unchanged when it is not a code.
 */
export function formatSku(value) {
  if (!value) return value
  const text = String(value)
  return /^[!-~]+$/.test(text) ? text.toUpperCase() : text
}

const percentFormats = new Map()

/**
 * 12.3456 -> "12.35%" (the value is already 0–100, not a 0–1 ratio), with no
 * space before the sign. A missing value renders as an em dash.
 *
 * @param {number|string|null|undefined} value
 * @param {number} [fractionDigits] 2 by default; a chart's tooltip uses 1.
 */
export function formatPercent(value, fractionDigits = 2) {
  const amount = figureOf(value)
  if (amount === null) return '—'
  if (!percentFormats.has(fractionDigits)) {
    percentFormats.set(
      fractionDigits,
      new Intl.NumberFormat('en-US', {
        minimumFractionDigits: fractionDigits,
        maximumFractionDigits: fractionDigits,
      }),
    )
  }
  return `${percentFormats.get(fractionDigits).format(amount)}%`
}

/**
 * The English word for a count: `plural(5, ['reason', 'reasons'])` → "reasons".
 * One is singular; everything else, zero included, is plural.
 *
 * @param {number} n
 * @param {[string, string]} forms Singular, then plural.
 */
export function plural(n, [one, other]) {
  return Math.abs(n) === 1 ? one : other
}
