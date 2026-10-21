/**
 * The page's shared formatting: ratios as percentages, and the series hues.
 *
 * Money goes straight through `formatMoney` with the response's currency, so
 * every figure carries its own sign like the rest of the app.
 */
import { formatPercent } from '@/core/utils/format'

/** A 0–1 ratio as the app prints percentages; `null` is an em dash, not «0%». */
export function ratioPct(ratio) {
  return ratio === null || ratio === undefined ? '—' : formatPercent(ratio * 100)
}

/**
 * Fixed hues, by meaning — the dataviz palette's first three slots, validated
 * together for colour-blind separation (worst adjacent ΔE 9.2). «Расход» and
 * «Поиск» share slot 1, «Промо-бонусы» and «Полки» slot 2, «Каталог» slot 3;
 * DRR takes the pink the monitoring charts give «ДРР от продаж».
 *
 * Hex rather than a token because ECharts and the SVG pies need a literal.
 */
export const SERIES = {
  spend: '#2A78D6',
  bonus: '#EB6834',
  drr: '#E87BA4',
}

export const ZONE_COLORS = {
  search: '#2A78D6',
  shelves: '#EB6834',
  catalog: '#1BAF7A',
}

/** DRR above this is printed in the negative tone. */
export const DRR_ALARM = 0.2

/** "2026-07-05" -> "05.07.2026". */
export function dateRu(iso) {
  return iso ? iso.split('-').reverse().join('.') : '—'
}
