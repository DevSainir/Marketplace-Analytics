/**
 * The two things every piece of the block formats the same way: a ratio as a
 * percentage, and the hue of each half of a split.
 *
 * Money goes straight through `formatMoney` with the datapack's currency, so
 * every figure carries its own sign like the rest of the app.
 */
import { formatPercent } from '@/core/utils/format'

/** A 0–1 ratio as the app prints percentages; `null` is an em dash, not «0%». */
export function ratioPct(ratio) {
  return ratio === null || ratio === undefined ? '—' : formatPercent(ratio * 100)
}

/**
 * The block's two-way splits share one pair of hues: the FIRST half of each
 * (the seller's own balance, the search zone) blue, the second (WB's promo
 * bonus, shelves and the rest) orange — the same pair the one-pager used and
 * the monitoring charts give «Корзины» and «Заказы».
 *
 * Hex rather than a token because ECharts paints on a canvas and cannot read a
 * custom property; the bars use the same constants so chart and bars agree.
 */
export const SPLIT_COLORS = ['#2A78D6', '#EB6834']

/** ДРР above this is printed in the negative tone — the one-pager's threshold. */
export const DRR_ALARM = 0.2
