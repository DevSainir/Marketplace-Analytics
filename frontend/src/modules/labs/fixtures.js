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

const rand = seeded(20260825)

const DAY_COUNT = 10
const END = new Date(Date.UTC(2026, 7, 24))

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

/**
 * Which buckets actually carry data on a given day.
 *
 * A seller runs ONE campaign at a time, not four in parallel, so the real
 * ribbon is mostly empty: one traffic group filled, «Общая»/«Органика» rolled
 * up beside it, everything else blank. Filling every bucket — as the first
 * pass did — made the table look busy and, worse, made it lie about how the
 * account is actually run.
 *
 * Indices are into TRAFFIC_COLUMNS. «Каталог» of the unified bid (index 2) is
 * never here: it is a legacy WB zone kept for workbook parity and always empty.
 */
const CAMPAIGNS = [
  [0, 1], // Единая ставка — Поиск + Полки
  [3, 4], // Руч. поиск — Поиск + Каталог
  [5], // Руч. полки
  [6, 7], // CPC — Поиск + Полки
]

const ROLLUPS = [TOTAL, ORGANIC]

/**
 * The live bucket set per day, decided ONCE so every metric row agrees — and
 * with it the day's «Доля трафика» split, which must be decided once for the
 * same reason. Drawing the head share inside the per-bucket loop gave each
 * bucket its own `rand()` and the row added up to 97,58 % instead of 100 %.
 */
const LIVE_BY_DAY = Array.from({ length: DAY_COUNT }, (_, d) => {
  const campaign = CAMPAIGNS[d % CAMPAIGNS.length]
  const head = campaign.length === 1 ? 100 : 88 + rand() * 8
  const shares = campaign.length === 1 ? [100] : [head, 100 - head]
  return { campaign, shares, live: new Set([...campaign, ...ROLLUPS]) }
})

/** Flat day-major values, exactly as the backend emits them. */
function buildValues(key, { base, spread, ratio, totalOnly }) {
  const values = []
  for (let d = 0; d < DAY_COUNT; d += 1) {
    const { campaign, shares, live } = LIVE_BY_DAY[d]
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

export const product = {
  nm_id: 214839021,
  vendor_code: 'HD-OVER-BLK-M',
  title: 'Худи оверсайз утеплённое, чёрное',
  window: WINDOW,
  matrix: {
    days: dayIsos,
    buckets: BUCKETS,
    rows: Object.entries(METRICS).map(([key, spec]) => ({ key, values: buildValues(key, spec) })),
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
  // «Корзины»/«Заказы» cells have no hover tooltip at all — which is why the
  // sandbox showed none.
  matrix_base: {
    days: dayIsos.map((day, i) => ({
      day,
      buckets: {
        uni_search: {
          assoc_exact: i % 2 === 0,
          assoc_skus: [
            {
              nm_id: 214839021,
              vendor_code: 'HD-OVER-BLK-M',
              add_to_cart: 18 + i,
              orders: 6 + (i % 3),
            },
            { nm_id: 214839044, vendor_code: 'HD-OVER-GRY-L', add_to_cart: 9 + (i % 4), orders: 3 },
            { nm_id: 214839051, vendor_code: 'HD-OVER-BLK-L', add_to_cart: 5, orders: 2 },
          ],
        },
        total: {
          assoc_exact: true,
          assoc_skus: [
            { nm_id: 214839021, vendor_code: 'HD-OVER-BLK-M', add_to_cart: 41 + i, orders: 14 },
            { nm_id: 214839044, vendor_code: 'HD-OVER-GRY-L', add_to_cart: 22, orders: 7 },
            { nm_id: 214839051, vendor_code: 'HD-OVER-BLK-L', add_to_cart: 11, orders: 4 },
          ],
        },
      },
    })),
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
}

/** The real builder, on the real payload — no sandbox-specific shortcut. */
export const matrixView = buildMetricsMatrix(product)

/* ---------------------------------------------------------------- header */

export const skuList = [
  { nm_id: 214839021, vendor_code: 'HD-OVER-BLK-M', title: 'Худи оверсайз утеплённое, чёрное' },
  { nm_id: 214839044, vendor_code: 'HD-OVER-GRY-L', title: 'Худи оверсайз утеплённое, серое' },
  { nm_id: 551088230, vendor_code: 'JG-SPORT-NVY', title: 'Джоггеры спортивные, тёмно-синие' },
  { nm_id: 610447701, vendor_code: 'TS-BASIC-WHT', title: 'Футболка базовая, белая' },
  { nm_id: 772900115, vendor_code: 'SH-SPORT-BLK', title: 'Шорты спортивные, чёрные' },
]

export const pinnedSkus = [
  { nm_id: 214839021, vendor_code: 'HD-OVER-BLK-M', title: 'Худи, чёрное', color: '#4F39F6' },
  { nm_id: 214839044, vendor_code: 'HD-OVER-GRY-L', title: 'Худи, серое', color: '#0E9384' },
  { nm_id: 551088230, vendor_code: 'JG-SPORT-NVY', title: 'Джоггеры', color: '#C2700B' },
  { nm_id: 610447701, vendor_code: 'TS-BASIC-WHT', title: 'Футболка', color: '#D93A2B' },
  { nm_id: 772900115, vendor_code: 'SH-SPORT-BLK', title: 'Шорты', color: '#7C3AED' },
]

/* ----------------------------------------------------------------- stock */

const WAREHOUSES = [
  'Коледино',
  'Электросталь',
  'Казань',
  'Craft Тула',
  'Санкт-Петербург Уткина Заводь',
]
const SIZES = [
  { chrt_id: 900001, tech_size: 'S' },
  { chrt_id: 900002, tech_size: 'M' },
  { chrt_id: 900003, tech_size: 'L' },
  { chrt_id: 900004, tech_size: 'XL' },
]

export const SIZE_ORDER = SIZES

/** `StockDetail.cells`: one entry per size × warehouse. */
function stockCells(seed) {
  const r = seeded(seed)
  return SIZES.flatMap((size) =>
    WAREHOUSES.map((warehouse_name) => ({
      chrt_id: size.chrt_id,
      tech_size: size.tech_size,
      warehouse_name,
      quantity: Math.round(r() * 180),
    })),
  )
}

export const stockCompare = {
  left: { date: dayIsos[DAY_COUNT - 2], loading: false, stock: { cells: stockCells(11) } },
  right: { date: dayIsos[DAY_COUNT - 1], loading: false, stock: { cells: stockCells(29) } },
}

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
