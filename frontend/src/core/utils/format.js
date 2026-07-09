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

/** 12.3456 -> "12.35%" */
export function formatPercent(value) {
  return `${value.toFixed(2)}%`
}
