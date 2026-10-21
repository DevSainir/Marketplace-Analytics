/**
 * Three sample cards — the cards the sandbox opens on.
 *
 * Fixed per card: the nm IDs, vendor codes, titles, buyer ratings, sizes (with
 * WB-style chrt IDs) and one campaign ID per traffic group for the week
 * 18.09–25.09. They are sample values in the shape the backend sends, not
 * identifiers of live cards, so a WB link built from them need not open
 * anything. Everything else on the page for these cards — the metrics, the
 * stock — is synthesised, because the point is to click through, not to read
 * the numbers.
 *
 * `campaigns` is keyed by TRAFFIC_GROUPS `key`; the same campaign ran on every
 * day of the window, so one id per group covers all of it.
 */

/**
 * The settlement currency of the sample cards, so the sandbox's money labels are as
 * wide as the real page's — label width is part of what the sandbox compares.
 */
export const REAL_CURRENCY = 'KGS'

/** «42/170-177» × two heights — the curve every «Брюки бананы» card carries. */
function trouserSizes(firstChrt, heights) {
  const sizes = []
  let chrt = firstChrt
  for (const waist of [42, 44, 46, 48, 50, 52, 54]) {
    for (const height of heights) {
      sizes.push({ chrt_id: chrt, tech_size: `${waist}/${height}` })
      chrt += 1
    }
  }
  return sizes
}

export const REAL_SKUS = [
  {
    nm_id: 953770957,
    vendor_code: 'M-TRX01-BLK',
    title: 'Брюки прямые базовые',
    feedback_rating: 4.7,
    campaigns: { uni: 97455860, manual_search: 97455887 },
    color: '#E3DEFF',
    // This card's sizes were added in three batches, so its chrt IDs do not
    // run in one sequence like the other two.
    sizes: [
      ...[42, 44, 46, 48, 50, 52, 54].map((w, i) => ({
        chrt_id: 965033855 + i,
        tech_size: `${w}/170-177`,
      })),
      ...[42, 44, 46, 48, 50, 52, 54].map((w, i) => ({
        chrt_id: 965584984 + i,
        tech_size: `${w}/178-185`,
      })),
      ...[42, 44, 46, 48].map((w, i) => ({ chrt_id: 1966908335 + i, tech_size: `${w}/162-169` })),
    ],
  },
  {
    nm_id: 995716075,
    vendor_code: 'M-TRX01-CHK',
    title: 'Брюки прямые базовые',
    feedback_rating: 4.8,
    campaigns: { uni: 97455881, manual_search: 97455888 },
    color: '#D3E8DE',
    sizes: trouserSizes(1960866418, ['170-177', '178-185']),
  },
  {
    nm_id: 1944208580,
    vendor_code: 'M-STX01-BLK',
    title: 'Брюки прямые базовые',
    feedback_rating: 4.8,
    campaigns: { uni: 97455932 },
    color: '#F2E4CC',
    sizes: trouserSizes(1997288470, ['170-177', '178-185']),
  },
]
