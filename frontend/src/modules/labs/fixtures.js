/**
 * The sandbox's data, shaped exactly like the backend's.
 *
 * The components under `labs/components/` are VERBATIM copies of the
 * monitoring ones — same markup, same props, same behaviour — so the sandbox
 * cannot hand them a convenient shape. It synthesises a `SkuDetailResponse`
 * and runs it through the REAL `buildMetricsMatrix`, which is copied too. If
 * the matrix ever renders differently from /monitoring, the difference is in
 * the stylesheet, which is the whole point of the page.
 *
 * Deterministic (a seeded LCG, not `Math.random`): the page has to look
 * identical on every reload or two screenshots cannot be compared.
 */
import { TRAFFIC_COLUMNS, buildMetricsMatrix } from '@/modules/labs/metricsMatrix'
import { REAL_CURRENCY, REAL_SKUS } from '@/modules/labs/realSkus'
import { buildStockDays } from '@/modules/labs/stockFixtures'

/** Mulberry32 — small, fast, same sequence every run. */
function seeded(seed) {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/**
 * The window is the week the sample campaign ids are dated to (`realSkus.js`),
 * so a campaign link would open on the same days the table shows.
 */
const DAY_COUNT = 8
const END = new Date(Date.UTC(2026, 8, 25))

const dayIsos = Array.from({ length: DAY_COUNT }, (_, i) => {
  const d = new Date(END)
  d.setUTCDate(d.getUTCDate() - (DAY_COUNT - 1 - i))
  return d.toISOString().slice(0, 10)
})

export const WINDOW = { start: dayIsos[0], end: dayIsos[DAY_COUNT - 1] }

/** Backend bucket order — the matrix indexes values by it. */
const BUCKETS = TRAFFIC_COLUMNS.map((c) => c.key)

const TOTAL = BUCKETS.indexOf('total')
const ORGANIC = BUCKETS.indexOf('organic')

/**
 * Per-metric magnitude. Ratios are NOT scaled up in the rollup buckets —
 * summing the zones of a percentage is meaningless, and scaling one produces
 * «Процент выкупа 197 %», which is not a rough number but an impossible one.
 */
const METRICS = {
  traffic_share: { base: 14, spread: 9, ratio: true },
  spend: { base: 1480, spread: 900 },
  views: { base: 8400, spread: 5200 },
  ctr: { base: 3.1, spread: 1.8, ratio: true },
  cpm: { base: 168, spread: 74, ratio: true },
  cpc: { base: 12.4, spread: 6, ratio: true },
  clicks: { base: 246, spread: 130 },
  carts: { base: 38, spread: 22 },
  cart_conversion: { base: 11.8, spread: 5, ratio: true },
  orders: { base: 12, spread: 7 },
  order_conversion: { base: 4.6, spread: 2.2, ratio: true },
  order_sum: { base: 39400, spread: 21000 },
  buyout_sum: { base: 27100, spread: 15000 },
  cost_per_order: { base: 244, spread: 120, ratio: true },
  cost_per_cart: { base: 96, spread: 44, ratio: true },
  drr_orders: { base: 12.6, spread: 6, ratio: true },
  drr_sales: { base: 18.4, spread: 8, ratio: true },
  buyout_percent: { base: 71, spread: 12, ratio: true, totalOnly: true },
  seller_price: { base: 4190, spread: 240, totalOnly: true },
  customer_price: { base: 3180, spread: 210, totalOnly: true },
  spp: { base: 24, spread: 6, ratio: true, totalOnly: true },
  stock_quantity: { base: 693, spread: 180, totalOnly: true },
  stock_to_client: { base: 84, spread: 40, totalOnly: true },
  stock_from_client: { base: 21, spread: 14, totalOnly: true },
  stock_total: { base: 798, spread: 190, totalOnly: true },
  // The viewed card's own share of «Корзины»/«Заказы». The backend emits these
  // only where they differ from the campaign total; the gap between the two is
  // what the associative-conversion tooltip breaks down per size/colour.
  carts_sku: { base: 26, spread: 14 },
  orders_sku: { base: 8, spread: 5 },
}

/** The zone buckets each campaign group delivers into (indices into TRAFFIC_COLUMNS). */
const GROUP_BUCKETS = {
  uni: [0, 1], // unified bid — search + shelves
  manual_search: [2, 3], // manual search — search + catalogue
  manual_shelves: [4], // manual shelves
  cpc: [5, 6], // CPC — search + shelves
}

const ROLLUPS = [TOTAL, ORGANIC]

/**
 * The live bucket set of one day, decided ONCE so every metric row agrees —
 * and with it the day's «Доля трафика» split, which must be decided once for
 * the same reason. Drawing the share inside the per-bucket loop gave each
 * bucket its own `rand()` and the row added up to 97,58 % instead of 100 %.
 * The first bucket of each campaign (its «Поиск») takes the lion's share.
 */
function liveDay(groupKeys, rand) {
  const campaign = groupKeys.flatMap((key) => GROUP_BUCKETS[key])
  const raw = campaign.map((b, i) =>
    GROUP_BUCKETS[groupKeys.find((k) => GROUP_BUCKETS[k].includes(b))][0] === b
      ? 6 + rand() * 4
      : 0.4 + rand() * (i + 1) * 0.3,
  )
  const sum = raw.reduce((a, v) => a + v, 0)
  const shares = raw.map((v) => (v / sum) * 100)
  return { campaign, shares, live: new Set([...campaign, ...ROLLUPS]) }
}

/** Flat day-major values, exactly as the backend emits them. */
function buildValues(key, { base, spread, ratio, totalOnly }, liveByDay, rand) {
  const values = []
  for (const { campaign, shares, live } of liveByDay) {
    for (let b = 0; b < BUCKETS.length; b += 1) {
      const on = totalOnly ? b === TOTAL : live.has(b)
      if (!on) {
        values.push(null)
        continue
      }
      if (key === 'traffic_share') {
        // A share of the day's traffic belongs to a CAMPAIGN. «Общая» and
        // «Органика» are rollups of it, so the share has nothing to say there
        // and the real report leaves those two cells blank.
        const i = campaign.indexOf(b)
        values.push(i === -1 ? null : shares[i])
        continue
      }
      const rollup = !ratio && (b === TOTAL || b === ORGANIC)
      const v = Math.max(0, (base + (rand() - 0.5) * spread) * (rollup ? 2.6 : 1))
      // Counts are whole. The display formatter rounds anyway, but the
      // associative tooltip subtracts two RAW values — and a fraction there
      // renders as «17,671 ассоциативных конверсий», which is not a thing.
      values.push(ratio ? v : Math.round(v))
    }
  }
  return values
}

/**
 * One card's whole `SkuDetailResponse`, plus the sandbox-only extras the page
 * reads beside it: `campaign_ids` (the traffic-group links), `sizes` and `stock_days`.
 *
 * @param {object} spec
 * @param {Array<Record<string, number>>} spec.campaignsByDay per day, group key → advert id
 * @param {Array<{nm_id: number, vendor_code: string}>} spec.siblings the
 *   associative tooltip's other variants
 */
function buildProduct({
  nm_id,
  vendor_code,
  title,
  feedback_rating,
  sizes,
  campaignsByDay,
  siblings,
  seed,
}) {
  const rand = seeded(seed)
  const liveByDay = campaignsByDay.map((ids) => liveDay(Object.keys(ids), rand))
  const product = {
    nm_id,
    vendor_code,
    title,
    // `sales-funnel/products` → `product.feedbackRating`: the storefront's stars.
    feedback_rating,
    window: WINDOW,
    matrix: {
      days: dayIsos,
      buckets: BUCKETS,
      rows: Object.entries(METRICS).map(([key, spec]) => ({
        key,
        values: buildValues(key, spec, liveByDay, rand),
      })),
    },
    comments: {
      [dayIsos[0]]: {
        header: 'Подняли ставку',
        body: 'Единая хорошо отработала, однако показы на Главной странице всё ещё критично выше, чем полки в карточке.',
      },
      [dayIsos[1]]: { header: '', body: 'ЕДИНУЮ больше не крутим — плохо работает.' },
      [dayIsos[5]]: { header: 'Акция WB', body: 'Вошли в «Дни распродаж», СПП вырос до 29 %.' },
    },
    // Per-variant breakdowns, indexed by `<day>:<bucket>`. Without these the
    // «Корзины»/«Заказы» cells have no hover tooltip at all.
    matrix_base: {
      days: dayIsos.map((day, i) => {
        const skus = (lead) => [
          { nm_id, vendor_code, add_to_cart: lead + i, orders: 6 + (i % 3) },
          ...siblings.map((s, k) => ({ ...s, add_to_cart: 9 - k * 4 + (i % 4), orders: 3 - k })),
        ]
        const firstBucket = BUCKETS[liveByDay[i].campaign[0]]
        return {
          day,
          buckets: {
            [firstBucket]: { assoc_exact: i % 2 === 0, assoc_skus: skus(18) },
            total: { assoc_exact: true, assoc_skus: skus(41) },
          },
        }
      }),
    },
    day_actions: Object.fromEntries(
      dayIsos.map((iso, i) => [
        iso,
        {
          // Field names are the backend's, read straight off `MatrixActionsRow`:
          // guessing them is what left every «Действия» dropdown showing «—».
          first_rk_type: ['uni', 'manual_search', 'cpc'][i % 3],
          first_rk_budget: 2000 + i * 250,
          second_rk_type: i % 2 ? 'manual_shelves' : null,
          second_rk_budget: i % 2 ? 8000 + i * 90 : null,
          price_change: i % 3 === 0 ? 'up' : i % 3 === 1 ? 'down' : null,
          price_change_amount: i % 3 === 2 ? null : 25 + i,
        },
      ]),
    ),
    campaign_ids: Object.fromEntries(dayIsos.map((iso, i) => [iso, campaignsByDay[i]])),
    sizes,
    stock_days: buildStockDays({ sizes, days: dayIsos, rand, total: 90 * sizes.length }),
  }
  return product
}

/**
 * The made-up hoodie: the one card that runs ALL FOUR campaign types in turn,
 * one a day — a seller runs one campaign at a time, not four in parallel — so
 * every group of the table (including the one-column «Руч. полки») gets a day
 * with an id in it. Its campaign ids are made up, like the sample cards' ids in
 * `realSkus.js`, so a link opens WB's «кампания не найдена».
 */
const HOODIE_ADVERT_IDS = {
  uni: 38102455,
  manual_search: 38720514,
  manual_shelves: 37995102,
  cpc: 39610277,
}
const HOODIE_ROTATION = ['uni', 'manual_search', 'manual_shelves', 'cpc']

const HOODIE = buildProduct({
  nm_id: 214839021,
  vendor_code: 'HD-OVER-BLK-M',
  title: 'Худи оверсайз утеплённое, чёрное',
  feedback_rating: 4.6,
  sizes: [
    { chrt_id: 900001, tech_size: 'S' },
    { chrt_id: 900002, tech_size: 'M' },
    { chrt_id: 900003, tech_size: 'L' },
    { chrt_id: 900004, tech_size: 'XL' },
  ],
  campaignsByDay: dayIsos.map((_, d) => {
    const key = HOODIE_ROTATION[d % HOODIE_ROTATION.length]
    return { [key]: HOODIE_ADVERT_IDS[key] }
  }),
  siblings: [
    { nm_id: 214839044, vendor_code: 'HD-OVER-GRY-L' },
    { nm_id: 214839051, vendor_code: 'HD-OVER-BLK-L' },
  ],
  seed: 20260825,
})

const REAL = REAL_SKUS.map((sku, i) =>
  buildProduct({
    ...sku,
    campaignsByDay: dayIsos.map(() => sku.campaigns),
    siblings: REAL_SKUS.filter((s) => s !== sku)
      .slice(0, 2)
      .map(({ nm_id, vendor_code }) => ({ nm_id, vendor_code })),
    seed: 20260926 + i,
  }),
)

/** Every card the sandbox can show, by nm ID. */
export const products = Object.fromEntries([...REAL, HOODIE].map((p) => [p.nm_id, p]))

/** What the page opens on: the first sample card. */
export const DEFAULT_NM_ID = REAL[0].nm_id

/** The real builder, on the real payload — no sandbox-specific shortcut. */
export function matrixViewFor(product) {
  return buildMetricsMatrix(product, REAL_CURRENCY)
}

/* ---------------------------------------------------------------- header */

const FAKE_SKUS = [
  { nm_id: 214839021, vendor_code: 'HD-OVER-BLK-M', title: 'Худи оверсайз утеплённое, чёрное' },
  { nm_id: 551088230, vendor_code: 'JG-SPORT-NVY', title: 'Джоггеры спортивные, тёмно-синие' },
  { nm_id: 610447701, vendor_code: 'TS-BASIC-WHT', title: 'Футболка базовая, белая' },
]

export const skuList = [
  ...REAL_SKUS.map(({ nm_id, vendor_code, title }) => ({ nm_id, vendor_code, title })),
  ...FAKE_SKUS,
]

/** The sample cards first, each in its own tint (the /monitoring palette); the other made-up ones after, untinted. */
export const pinnedSkus = [
  ...REAL_SKUS.map(({ nm_id, vendor_code, color }) => ({
    nm_id,
    vendor_code,
    title: 'Брюки бананы',
    color,
  })),
  { nm_id: 214839021, vendor_code: 'HD-OVER-BLK-M', title: 'Худи, чёрное' },
  { nm_id: 551088230, vendor_code: 'JG-SPORT-NVY', title: 'Джоггеры' },
]

/* ----------------------------------------------------------- clusters */

export const clusterTableProps = {
  clusters: [
    {
      cluster: 'худи оверсайз',
      views: 184203,
      clicks: 4821,
      ctr: 2.62,
      orders: 214,
      spend: 58400,
      cpc: 12.1,
      avg_position: 4.2,
      days_count: 10,
    },
    {
      cluster: 'худи мужское зимнее',
      views: 96140,
      clicks: 2610,
      ctr: 2.71,
      orders: 118,
      spend: 31200,
      cpc: 11.9,
      avg_position: 6.8,
      days_count: 10,
    },
    {
      cluster: 'толстовка утеплённая',
      views: 61870,
      clicks: 1402,
      ctr: 2.27,
      orders: 54,
      spend: 18900,
      cpc: 13.5,
      avg_position: 11.4,
      days_count: 9,
    },
    {
      cluster: 'кофта тёплая чёрная',
      views: 28410,
      clicks: 610,
      ctr: 2.15,
      orders: 19,
      spend: 8100,
      cpc: 13.3,
      avg_position: null,
      days_count: 6,
    },
    {
      cluster: 'худи на флисе',
      views: 12980,
      clicks: 341,
      ctr: 2.63,
      orders: 11,
      spend: 4300,
      cpc: 12.6,
      avg_position: 18.9,
      days_count: 4,
    },
  ],
  clustersLoading: false,
  clustersError: null,
  loaded: true,
}
