/**
 * The page's shared formatting: ratios as percentages, and the series hues.
 *
 * Money goes straight through `formatMoney` with the response's currency, so
 * every figure carries its own sign like the rest of the app.
 */
import { formatPercent } from '@/core/utils/format'

/** A 0–1 ratio as the app prints percentages; `null` is an em dash, not "0%". */
export function ratioPct(ratio) {
  return ratio === null || ratio === undefined ? '—' : formatPercent(ratio * 100)
}

/**
 * Fixed hues, by meaning — the dataviz palette's first three slots, validated
 * together for colour-blind separation (worst adjacent ΔE 9.2). "Spend" and
 * "Search" share slot 1, "Promo bonuses" and "Shelves" slot 2, "Catalog" slot 3;
 * DRR takes the pink the monitoring charts give "ACoS (sales)".
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
