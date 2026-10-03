/**
 * The кабинет's ad spend over a window, cut by bid type, funding source and
 * placement zone.
 *
 * Three money sources feed the «Реклама» block, and they do not agree:
 *
 * * WB's deductions — the money actually taken, and what the margin is built
 *   on (that is the per-SKU half, `adsSkuRows.js`);
 * * the кабинет's spend history (`daily_kind`) — exact day, bid type, and
 *   whether the balance or WB's promo bonus paid;
 * * campaign statistics (`zones_daily`) — the only source that knows WHERE an
 *   impression was shown.
 *
 * Over the window the history and the statistics differ by ~1.2 %, so a zone is
 * applied as a SHARE of the history's money, never as its own sum: the block
 * would otherwise print two totals for the same spend.
 *
 * Ported from the finmodel one-pager (`labs/finmodel/tabs/adsData.js`) with the
 * arithmetic unchanged — only the DOM went away. Pure: datapack in, figures out.
 */

/** Campaign statistics name a bid type by its API key; the history by its label. */
export const KIND_BY_BID = { manual: 'Ручная Ставка', unified: 'Единая Ставка' }

/** A history row with no bid type still has to land in some row of the table. */
const UNTYPED = 'Без типа'

/**
 * Spend in [from, to]: total, split by source, and per bid type, largest first.
 *
 * @param {object} ads The datapack's `ads` block.
 * @param {string} from ISO day, inclusive.
 * @param {string} to ISO day, inclusive.
 * @returns {{total: number, balance: number, promo: number,
 *   kinds: Array<{name: string, total: number, balance: number, promo: number}>}}
 */
export function spendWindow(ads, from, to) {
  const out = { total: 0, balance: 0, promo: 0, kinds: [] }
  const byKind = {}
  for (const [day, kindName, source, amount] of ads.daily_kind ?? []) {
    if (day < from || day > to) continue
    const name = kindName || UNTYPED
    const kind = (byKind[name] ??= { name, total: 0, balance: 0, promo: 0 })
    kind.total += amount
    kind[source] += amount
    out.total += amount
    out[source] += amount
  }
  out.kinds = Object.values(byKind).sort((a, b) => b.total - a.total)
  return out
}

/**
 * The search share of spend in [from, to], overall and per bid type.
 *
 * A row with an unknown bid key still counts toward the overall share — it is
 * real spend — but cannot be attributed to a bid-type row.
 *
 * @returns {{share: number|null, days: number,
 *   byKind: Object<string, {search: number, rest: number, share: number}>}}
 *   `share` is `null` when the statistics hold nothing for the window.
 */
export function zoneShares(ads, from, to) {
  const out = { share: null, days: 0, byKind: {} }
  const total = { search: 0, rest: 0 }
  const byKind = {}
  const days = new Set()
  for (const [day, bid, search, rest] of ads.zones_daily ?? []) {
    if (day < from || day > to) continue
    days.add(day)
    total.search += search
    total.rest += rest
    const kind = KIND_BY_BID[bid]
    if (!kind) continue
    const sums = (byKind[kind] ??= { search: 0, rest: 0 })
    sums.search += search
    sums.rest += rest
  }
  out.days = days.size
  const sum = total.search + total.rest
  if (!sum) return out
  out.share = total.search / sum
  for (const [kind, sums] of Object.entries(byKind)) {
    const kindSum = sums.search + sums.rest
    if (kindSum) out.byKind[kind] = { ...sums, share: sums.search / kindSum }
  }
  return out
}

/**
 * The bid-type table: each kind's money with the zone share applied to it.
 *
 * @returns {Array<{name: string, total: number, part: number|null, balance: number,
 *   promo: number, search: number|null, rest: number|null, share: number|null}>}
 *   `search`/`rest`/`share` are `null` for a kind the statistics never saw.
 */
export function kindRows(window, zones) {
  return window.kinds.map((kind) => {
    const share = zones.byKind[kind.name]?.share ?? null
    return {
      ...kind,
      part: window.total ? kind.total / window.total : null,
      search: share === null ? null : kind.total * share,
      rest: share === null ? null : kind.total * (1 - share),
      share,
    }
  })
}

/**
 * The «Зоны показов» bars: the whole spend first, then each kind that has a
 * measured share. Parts are money, so a bar's two halves sum to its spend.
 *
 * @returns {Array<{label: string, search: number, rest: number}>} empty when
 *   the window has no zone statistics at all.
 */
export function zoneBars(window, zones) {
  if (zones.share === null) return []
  const bars = [
    {
      label: 'Вся реклама',
      search: window.total * zones.share,
      rest: window.total * (1 - zones.share),
    },
  ]
  for (const kind of window.kinds) {
    const measured = zones.byKind[kind.name]
    if (!measured) continue
    bars.push({
      label: kind.name,
      search: kind.total * measured.share,
      rest: kind.total * (1 - measured.share),
    })
  }
  return bars.filter((bar) => bar.search + bar.rest)
}

/**
 * Spend per day in [from, to], by source — the «Открутка по дням» chart.
 *
 * @returns {Array<{day: string, balance: number, promo: number}>}
 */
export function dailySpend(ads, from, to) {
  return (ads.daily ?? [])
    .filter(([day]) => day >= from && day <= to)
    .map(([day, balance, promo]) => ({ day, balance, promo }))
}

/**
 * What the reconciliation notes print. These figures describe the whole spend
 * file, not the chosen window — they are properties of how WB settles, which
 * is why the block states them independent of the period.
 */
export function reconciliation(ads) {
  const gaps = ads.gaps ?? []
  return {
    gaps,
    gapSpent: gaps.reduce((sum, gap) => sum + gap.spent, 0),
    residual: ads.residual,
    residualPct: ads.residual_pct,
    beforeWindow: ads.before_window,
    noArticle: ads.no_article || 0,
  }
}
