/**
 * What sort of advertising a campaign is, in the two words the fork has room for.
 *
 * The branches under "Test summary" used to carry the campaign's own name from
 * the WB seller portal. Sellers name campaigns for themselves — "M-BLK-2 auto
 * funnel Sep" — and under a figure that is four branches wide there is room for
 * about eight characters, so every branch read "M-B…" and the fork said nothing.
 * What the reader needs there is not WHICH campaign but WHAT KIND: "Unified"
 * buys a mixed placement at a CPM and "CPC" buys clicks, so a photo's CTR under
 * one is not comparable with its CTR under the other — which is the entire
 * reason the figures are split.
 *
 * The full name is not lost: it stays on the branch's `title`, a hover away.
 *
 * Spelled the way the backend spells the same four groups, because it is the
 * same seller reading both on the same day.
 */

/** Short label per `CampaignKind` — the backend's `kind` string. */
export const CAMPAIGN_KIND_LABELS = {
  uni: 'Unified',
  manual_search: 'Manual search',
  manual_shelves: 'Manual shelves',
  cpc: 'CPC',
  unknown: 'Advertising',
}

/**
 * What to call one campaign in a space two words wide.
 *
 * @param {{kind?: string, name?: string}} campaign As the detail endpoint sends it.
 * @returns {string} The kind's label; "Advertising" for a campaign WB no longer
 *   lists, which is an absence of an answer rather than a fifth kind.
 */
export function campaignKindLabel(campaign) {
  return CAMPAIGN_KIND_LABELS[campaign?.kind] ?? CAMPAIGN_KIND_LABELS.unknown
}
