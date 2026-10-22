/**
 * The result grid's data and wording, projected once and rendered twice.
 *
 * The desktop table and the narrow-screen pager show the same six figures for
 * the same photos; only the axis they run along differs. Keeping the projection
 * here — rather than in whichever component was written first — is what stops
 * the two from disagreeing about which photo is the leader or how a gap is
 * coloured, which is the failure mode a second copy always eventually produces.
 *
 * See `VariantResultsTable.vue` for why each derived row exists.
 */

import { formatNumber, formatPercent } from '@/core/utils/format'

/**
 * How far behind the leader still counts as close.
 *
 * Thresholds rather than a gradient, because the figure answers a yes/no
 * question — is this photo still a contender — and a gradient makes every value
 * look like a slightly different shade of the same answer. Ten percent is
 * inside the noise of a few thousand impressions; past thirty, no amount of
 * further data is going to rescue the photo.
 *
 * **The same three bands colour «Результат» and «Отклонение».** They are one
 * number written two ways — a relative gap and the same gap in points — so a
 * photo that reads «still close» on one line and «hopeless» on the other is the
 * table contradicting itself. Colouring every non-leader red, which is what
 * this did first, threw the distinction away entirely.
 */
const CLOSE_ENOUGH = -10
const CLEARLY_BEHIND = -30

/**
 * The rows of the grid, in the order they are read.
 *
 * No hints: the ⓘ beside each label was removed on 2026-09-28 at the owner's
 * request, and «Побед в раундах по CTR» with them — it did not earn its row.
 */
export const METRICS = [
  {
    key: 'views',
    label: 'Показов',
    kind: 'count',
  },
  {
    key: 'clicks',
    label: 'Кликов',
    kind: 'count',
  },
  {
    key: 'click_through',
    label: 'CTR',
    kind: 'percent',
  },
  {
    key: 'ctr_result',
    label: 'Результат',
    kind: 'result',
  },
  {
    key: 'ctr_gap',
    label: 'Отклонение CTR от лучшего',
    kind: 'gap',
  },
  {
    key: 'rounds_played',
    label: 'Кругов',
    kind: 'count',
  },
]

/**
 * The figures each photo shows — for the whole test, one lap, one campaign, or
 * one lap of one campaign.
 *
 * A lap is rebuilt from «История действий» rather than fetched: every turn
 * there already carries its lap, its photo and what it earned — per campaign
 * too — so filtering is arithmetic over data the page is already holding.
 *
 * A whole-test campaign view is NOT rebuilt: the backend has already computed
 * it, gap to the leader included, and that gap has to be measured against the
 * leader OF THAT CAMPAIGN. A photo can lead «Единая» and trail «CPC», which is
 * exactly what the unsplit row cannot show.
 *
 * `rounds_played` stays a per-campaign-whole-test figure rather than a per-lap
 * one: "laps in this lap" is always one.
 *
 * @param {object} test The test, as the detail endpoint returns it.
 * @param {number} round Lap to show, or 0 for the whole test.
 * @param {number} campaignId Campaign to show, or 0 for all of them together.
 * @returns {Array<object>} One entry per photo, in rotation order.
 */
export function buildColumns(test, round, campaignId = 0) {
  const variants = test?.variants ?? []
  if (!round && !campaignId) return variants
  if (!round) return variants.map((variant) => withCampaign(variant, campaignId))

  const byVariant = {}
  for (const turn of test.history ?? []) {
    if (turn.round_number !== round) continue
    const earned = countsOf(turn, campaignId)
    if (!earned) continue
    const seen = byVariant[turn.variant_id] ?? { views: 0, clicks: 0 }
    byVariant[turn.variant_id] = {
      views: seen.views + earned.views,
      clicks: seen.clicks + earned.clicks,
    }
  }

  const lap = variants.map((variant) => {
    const counts = byVariant[variant.variant_id] ?? { views: 0, clicks: 0 }
    const base = campaignId ? withCampaign(variant, campaignId) : variant
    return {
      ...base,
      views: counts.views,
      clicks: counts.clicks,
      click_through: counts.views ? (counts.clicks * 100) / counts.views : null,
    }
  })

  // The leader of this lap, so «Результат» compares within what is shown rather
  // than against a photo whose best hour was three laps ago.
  const best = Math.max(...lap.map((v) => v.click_through ?? -1))
  return lap.map((variant) => ({
    ...variant,
    ctr_gap: variant.click_through === null || best <= 0 ? null : best - variant.click_through,
    ctr_result:
      variant.click_through === null || best <= 0
        ? null
        : ((variant.click_through - best) * 100) / best,
  }))
}

/**
 * One photo as ONE campaign measured it.
 *
 * A photo the campaign never served reads as unmeasured — zero counts and a
 * null CTR — rather than as 0 %: it has not failed to be clicked, it has not
 * been shown.
 *
 * @param {object} variant A photo's whole-test row.
 * @param {number} campaignId The campaign to read it through.
 * @returns {object} The same row with that campaign's figures.
 */
function withCampaign(variant, campaignId) {
  const slice = (variant.campaigns ?? []).find((row) => row.campaign_id === campaignId)
  return {
    ...variant,
    views: slice?.views ?? 0,
    clicks: slice?.clicks ?? 0,
    click_through: slice?.click_through ?? null,
    ctr_gap: slice?.ctr_gap ?? null,
    ctr_result: slice?.ctr_result ?? null,
    rounds_played: slice?.rounds_played ?? 0,
  }
}

/**
 * What one turn earned, through one campaign or through all of them.
 *
 * @param {object} turn One «История действий» row.
 * @param {number} campaignId The campaign, or 0 for the turn's own totals.
 * @returns {{views: number, clicks: number}|null} Null when that campaign
 *   brought nothing in this turn — which is not the same as zero, and is what
 *   keeps a switched-off campaign out of the laps it did not run.
 */
function countsOf(turn, campaignId) {
  if (!campaignId) return { views: turn.views, clicks: turn.clicks }
  const slice = (turn.campaigns ?? []).find((row) => row.campaign_id === campaignId)
  return slice ? { views: slice.views, clicks: slice.clicks } : null
}

/**
 * The best measured photo still in the rotation, or null.
 *
 * An excluded photo cannot lead a comparison it has left — its numbers stay on
 * the table as the record of why it was excluded, not as a bar for the others.
 *
 * Compared as numbers, explicitly: the backend's ratios are `Decimal` and arrive
 * as strings (`"11.24"`), and two strings compare by their first character. That
 * crowned 8,92 % over 11,24 % in a running test —
 * invisible for as long as every CTR had one digit before the comma.
 *
 * @param {Array<object>} columns Projected photos.
 * @returns {string|null} The leading variant id.
 */
export function leaderOf(columns) {
  const measured = columns.filter((v) => v.click_through != null && !v.is_excluded)
  if (!measured.length) return null
  return measured.reduce((a, b) => (Number(b.click_through) > Number(a.click_through) ? b : a))
    .variant_id
}

/** «Главное» for the captured photo, «Вариант N» for an upload. */
export function variantTitle(variant) {
  return variant.is_original ? 'Главное' : `Вариант ${variant.position}`
}

/** A count; «—» when there is none — an unknown is not a zero (see `core/utils/format`). */
export const count = formatNumber

/** A percentage as the WB seller portal writes it, «12,35%» (see `core/utils/format`). */
export const percent = formatPercent

/**
 * A whole percent, with no signed zero.
 *
 * `Math.round` is applied before the sign is read, so a photo 0.3 % behind
 * shows «0%» rather than «-0%» — a minus in front of a zero says the photo is
 * behind by an amount too small to print, which is not what a reader takes
 * from it.
 */
function wholePercent(value) {
  const rounded = Math.round(Number(value))
  return `${rounded === 0 ? 0 : rounded}%`
}

/**
 * One figure: its text, and the tone it should be read in.
 *
 * A **tone**, not a class. Each rendering owns its own stylesheet and colours
 * the value through that sheet's modifier — `.ab-grid__value--negative` and so
 * on. Handing back a bare `text-status-*` utility here is what this did first,
 * and it silently did nothing: the scoped `.ab-grid__value` already sets a
 * colour and carries the scope attribute, so it outranks the utility and the
 * table rendered every figure in plain black. The design system records this
 * trap; it is worth not walking into twice.
 *
 * @param {object} variant A projected photo.
 * @param {object} metric One entry of {@link METRICS}.
 * @param {{leaderId: string|null}} context The comparison the figure is read
 *   against.
 * @returns {{text: string, tone: string}} `tone` is one of `''`, `'positive'`,
 *   `'warning'`, `'negative'`, `'muted'` or `'best'`.
 */
export function cellFor(variant, metric, { leaderId }) {
  const value = variant[metric.key]

  if (metric.kind === 'count') return { text: count(value), tone: '' }
  if (metric.kind === 'percent') return { text: percent(value), tone: '' }

  // «Результат» — the gap as a share of the leader's click-through. The leader
  // shows a plain green zero: it is exactly zero behind itself, and the word
  // belongs on the other line.
  if (metric.kind === 'result') {
    if (value === null || value === undefined) return { text: '—', tone: 'muted' }
    return { text: wholePercent(value), tone: band(value) }
  }

  // «Отклонение» — the only kind left: the same gap in points, and where the
  // leader is NAMED. One row carries the number, the other carries the verdict;
  // putting both on the same line leaves the other with nothing to say.
  if (variant.variant_id === leaderId) return { text: 'Лучший', tone: 'best' }
  if (value === null || value === undefined) return { text: '—', tone: 'muted' }
  return { text: `${percent(value)} ↓`, tone: band(variant.ctr_result) }
}

/**
 * Green, amber or red for one gap.
 *
 * @param {number|null} gap Click-through relative to the leader, in percent.
 * @returns {string} The tone name, or `'muted'` when there is nothing to say.
 */
function band(gap) {
  if (gap === null || gap === undefined) return 'muted'
  const value = Number(gap)
  if (value >= CLOSE_ENOUGH) return 'positive'
  if (value >= CLEARLY_BEHIND) return 'warning'
  return 'negative'
}
