/**
 * The page's shared formatting: ratios, money in the kit's short form, dates.
 *
 * The lab page wears the Bold Clarity kit, so its figures are the kit's —
 * «2,4 млн», «450 тыс» — not the app's full «2 412 345». The sign is still the
 * app's (`currencySign`: «с», «₽»), so a figure here and the same figure on
 * /advertising name their currency the same way.
 */
import { currencySign, formatPercent } from '@/core/utils/format'
import { BC } from '@/modules/labs/advertising/bold/charts'

/** A 0–1 ratio as the app prints percentages; `null` is an em dash, not «0%». */
export function ratioPct(ratio) {
  return ratio === null || ratio === undefined ? '—' : formatPercent(ratio * 100)
}

/**
 * `BC.money` in the response's currency. The kit keeps its currency in one
 * module-level variable, so it is set on every call rather than once — two
 * кабинеты in two currencies can be on screen one after the other.
 */
export function shortMoney(value, currency) {
  BC.setCurrency(currencySign(currency).trim())
  return BC.money(value).trim()
}

/** {@link shortMoney} split for `.num-xl`/`.num-l`: the figure, then `<small>` units. */
export function bigMoney(value, currency) {
  return BC.bigNum(shortMoney(value, currency))
}

/** ДРР above this is printed in the negative tone, and turns the headline dark. */
export const DRR_ALARM = 0.2

/** "2026-07-05" -> "05.07.2026". */
export function dateRu(iso) {
  return iso ? iso.split('-').reverse().join('.') : '—'
}

const dayMonth = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short' })

/** "2026-07-05" -> "5 июл." — for a period said in one line. */
export function dateShort(iso) {
  return iso ? dayMonth.format(new Date(`${iso}T00:00:00`)) : '—'
}
