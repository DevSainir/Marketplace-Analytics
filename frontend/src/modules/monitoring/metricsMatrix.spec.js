import { formatCurrency, formatNumber } from '@/core/utils/format'
import {
  TRAFFIC_COLUMNS,
  TRAFFIC_GROUPS,
  buildMetricsMatrix,
  isoDateRange,
} from '@/modules/monitoring/metricsMatrix'

describe('isoDateRange', () => {
  it('builds an inclusive ascending sequence', () => {
    expect(isoDateRange('2026-06-28', '2026-07-02')).toEqual([
      '2026-06-28',
      '2026-06-29',
      '2026-06-30',
      '2026-07-01',
      '2026-07-02',
    ])
  })

  it('returns [] for an inverted or invalid window', () => {
    expect(isoDateRange('2026-07-02', '2026-07-01')).toEqual([])
    expect(isoDateRange('oops', '2026-07-01')).toEqual([])
  })
})

describe('traffic column structure', () => {
  it('has 7 leaf columns matching the workbook zones', () => {
    expect(TRAFFIC_COLUMNS.map((c) => c.zone)).toEqual([
      'Поиск',
      'Полки',
      'Каталог',
      'Поиск',
      'Полки',
      'Общая',
      'Органика',
    ])
  })

  it('group spans cover exactly the leaf columns', () => {
    const spanned = TRAFFIC_GROUPS.reduce((sum, g) => sum + g.span, 0)
    expect(spanned).toBe(TRAFFIC_COLUMNS.length)
  })
})

const PRODUCT = {
  nm_id: 1,
  window: { start: '2026-07-01', end: '2026-07-02' },
  funnel: [
    {
      stat_date: '2026-07-01',
      open_count: 1000,
      cart_count: 100,
      order_count: 40,
      order_sum: 52000,
      buyout_count: 10,
      buyout_sum: 13000,
    },
    // 2026-07-02 has no funnel row (gap day)
  ],
  advertising: [
    {
      campaign_id: 11,
      daily: [
        { stat_date: '2026-07-01', app_type: 1, views: 1000, clicks: 80, add_to_cart: 20, spend: 500, orders: 8 },
        { stat_date: '2026-07-01', app_type: 32, views: 1000, clicks: 20, add_to_cart: 10, spend: 300, orders: 2 },
      ],
    },
    {
      campaign_id: 22,
      daily: [{ stat_date: '2026-07-01', app_type: 1, views: 500, clicks: 25, add_to_cart: 5, spend: 200, orders: 5 }],
    },
  ],
}

const COLS = TRAFFIC_COLUMNS.length
const col = (key) => TRAFFIC_COLUMNS.findIndex((c) => c.key === key)

/** Cell for metric `rowKey` on day index `d` in traffic column `colKey`. */
function cell(matrix, rowKey, d, colKey) {
  return matrix.rows.find((r) => r.key === rowKey).values[d * COLS + col(colKey)]
}

describe('buildMetricsMatrix', () => {
  it('spans the whole window with full-date section labels, 7 cells per day', () => {
    const matrix = buildMetricsMatrix(PRODUCT)
    expect(matrix.days.map((d) => d.label)).toEqual(['01.07.2026', '02.07.2026'])
    for (const row of matrix.rows) expect(row.values).toHaveLength(2 * COLS)
  })

  it('keeps the workbook row order', () => {
    const matrix = buildMetricsMatrix(PRODUCT)
    expect(matrix.rows.map((r) => r.key)).toEqual([
      'traffic_share',
      'spend',
      'views',
      'ctr',
      'cpm',
      'cpc',
      'clicks',
      'carts',
      'cart_conversion',
      'orders',
      'order_conversion',
      'order_sum',
      'buyout_sum',
      'cost_per_order',
      'cost_per_cart',
      'drr_orders',
      'drr_sales',
      'buyout_percent',
    ])
  })

  it('fills «Общая» with workbook formulas (ads summed across campaigns)', () => {
    const matrix = buildMetricsMatrix(PRODUCT)
    expect(cell(matrix, 'spend', 0, 'total')).toBe(formatCurrency(1000)) // 500+300+200
    expect(cell(matrix, 'views', 0, 'total')).toBe(formatNumber(2500))
    expect(cell(matrix, 'cpc', 0, 'total')).toBe(formatCurrency(8)) // 1000 / 125 ad clicks
    expect(cell(matrix, 'clicks', 0, 'total')).toBe(formatNumber(1000)) // card opens
    expect(cell(matrix, 'cart_conversion', 0, 'total')).toBe('10,00%')
    expect(cell(matrix, 'cost_per_order', 0, 'total')).toBe(formatCurrency(25)) // 1000/40
    expect(cell(matrix, 'drr_orders', 0, 'total')).toBe('1,92%') // 1000/52000*100
    expect(cell(matrix, 'buyout_percent', 0, 'total')).toBe('25,00%') // 10/40
    // Mixed zones: the workbook leaves CTR/CPM without an «Общая» value.
    expect(cell(matrix, 'ctr', 0, 'total')).toBe('—')
    expect(cell(matrix, 'cpm', 0, 'total')).toBe('—')
  })

  it('derives «Органика» as общая − реклама', () => {
    const matrix = buildMetricsMatrix(PRODUCT)
    expect(cell(matrix, 'clicks', 0, 'organic')).toBe('875') // 1000-125
    expect(cell(matrix, 'carts', 0, 'organic')).toBe('65') // 100-35
    expect(cell(matrix, 'orders', 0, 'organic')).toBe('25') // 40-15
    // Ad-only metrics have no organic reading.
    expect(cell(matrix, 'spend', 0, 'organic')).toBe('—')
  })

  it('keeps type/zone columns empty until placements are ingested', () => {
    const matrix = buildMetricsMatrix(PRODUCT)
    for (const key of ['uni_search', 'uni_shelves', 'uni_catalog', 'manual_search', 'manual_shelves']) {
      expect(cell(matrix, 'spend', 0, key)).toBe('—')
      expect(cell(matrix, 'orders', 0, key)).toBe('—')
    }
    expect(cell(matrix, 'traffic_share', 0, 'total')).toBe('—') // no traffic-share source yet
  })

  it('renders «—» for gap days instead of errors', () => {
    const matrix = buildMetricsMatrix(PRODUCT)
    expect(cell(matrix, 'spend', 1, 'total')).toBe('—')
    expect(cell(matrix, 'clicks', 1, 'total')).toBe('—')
    expect(cell(matrix, 'clicks', 1, 'organic')).toBe('—')
  })

  it('returns an empty matrix without a window', () => {
    expect(buildMetricsMatrix(null)).toEqual({ days: [], rows: [] })
  })
})
