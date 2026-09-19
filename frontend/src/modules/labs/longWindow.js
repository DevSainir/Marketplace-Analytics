/**
 * SANDBOX — a year of days, for the two fit-to-the-card chart experiments.
 *
 * `fixtures.js` is ten days wide, which is the window the rest of the sandbox
 * is about: at ten days every layout looks fine, and the question these charts
 * exist to answer («что делать с кварталом и с годом») cannot be asked of it.
 *
 * Deliberately shaped rather than uniformly random, because a flat noise band
 * hides exactly the failure the layouts are being judged on. This is the shape
 * a real card has: a launch spike, a long quiet middle where the card sold
 * almost nothing, and a rise over the last two months. If a layout cannot show
 * you where the quiet stretch began and ended, it has failed at a year.
 *
 * Only the `total` bucket is filled. The traffic zones are what the matrix
 * TABLE is read through, and nothing on this block reads them — the chart takes
 * `bucket: 'total'` for every metric it offers.
 */
import { TRAFFIC_COLUMNS, buildMetricsMatrix } from '@/modules/labs/metricsMatrix'

/** Mulberry32 — the same sequence every reload, so two screenshots compare. */
function seeded(seed) {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

const rand = seeded(20260919)

/** A full year, ending on the sandbox's «today». */
const DAY_COUNT = 365
const END = new Date(Date.UTC(2026, 8, 19))

const dayIsos = Array.from({ length: DAY_COUNT }, (_, index) => {
  const day = new Date(END)
  day.setUTCDate(day.getUTCDate() - (DAY_COUNT - 1 - index))
  return day.toISOString().slice(0, 10)
})

export const LONG_WINDOW = { start: dayIsos[0], end: dayIsos[DAY_COUNT - 1] }

const BUCKETS = TRAFFIC_COLUMNS.map((column) => column.key)
const TOTAL = BUCKETS.indexOf('total')

/**
 * How busy the card is on a given day, 0–1.
 *
 * Three acts — a launch that fades, a dead middle, a rise — plus a weekly
 * rhythm, because a real card's weekend is visibly not its Tuesday and a
 * weekly fold has to have something to fold.
 */
function intensity(index) {
  const t = index / (DAY_COUNT - 1)
  const launch = Math.exp(-(((t - 0.04) / 0.06) ** 2))
  const quiet = 0.06
  const revival = t < 0.6 ? 0 : ((t - 0.6) / 0.4) ** 1.6
  const weekday = (new Date(`${dayIsos[index]}T00:00:00Z`).getUTCDay() + 6) % 7
  const weekly = weekday >= 5 ? 0.78 : 1
  return (quiet + launch * 0.9 + revival) * weekly
}

/** Metric magnitudes at full intensity; ratios do not scale with volume. */
const METRICS = {
  spend: { base: 2600 },
  views: { base: 14000 },
  clicks: { base: 420 },
  carts: { base: 62 },
  orders: { base: 24 },
  ctr: { base: 3.0, ratio: true, spread: 1.1 },
  cpm: { base: 180, ratio: true, spread: 60 },
  cpc: { base: 12.5, ratio: true, spread: 5 },
  cart_conversion: { base: 12.4, ratio: true, spread: 4 },
  order_conversion: { base: 4.1, ratio: true, spread: 1.6 },
  buyout_percent: { base: 71, ratio: true, spread: 12 },
  drr_orders: { base: 18, ratio: true, spread: 7 },
  drr_sales: { base: 24, ratio: true, spread: 9 },
  seller_price: { base: 3190, ratio: true, spread: 240 },
  customer_price: { base: 2410, ratio: true, spread: 190 },
  // A LEVEL, not a flow: this is the one metric a weekly fold must average
  // rather than sum — see `chartScaling.js`.
  stock_quantity: { base: 740, ratio: true, spread: 420 },
}

/** Flat day-major values, exactly as the backend emits them. */
function buildValues(spec) {
  const values = []
  for (let day = 0; day < DAY_COUNT; day += 1) {
    const scale = spec.ratio ? 1 : intensity(day)
    const jitter = (rand() - 0.5) * (spec.spread ?? spec.base * 0.35)
    const value = Math.max(0, spec.base * scale + jitter * (spec.ratio ? 1 : scale))
    for (let bucket = 0; bucket < BUCKETS.length; bucket += 1) {
      values.push(bucket === TOTAL ? (spec.ratio ? value : Math.round(value)) : null)
    }
  }
  return values
}

const longProduct = {
  nm_id: 214839021,
  vendor_code: 'HD-OVER-BLK-M',
  title: 'Худи оверсайз утеплённое, чёрное',
  window: LONG_WINDOW,
  matrix: {
    days: dayIsos,
    buckets: BUCKETS,
    rows: Object.entries(METRICS).map(([key, spec]) => ({ key, values: buildValues(spec) })),
  },
}

/** The real builder, on the real payload — no sandbox-specific shortcut. */
export const longMatrixView = buildMetricsMatrix(longProduct)
