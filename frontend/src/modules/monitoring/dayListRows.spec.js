import {
  blockDayItems,
  dayLabelWithWeekday,
  metricDayItems,
} from '@/modules/monitoring/dayListRows'
import { COLUMNS_PER_DAY } from '@/modules/monitoring/metricsMatrix'

/**
 * A metric row as the matrix builds it: cells flat in day-major order,
 * `cells[day * COLUMNS_PER_DAY + column]` over TRAFFIC_COLUMNS.
 * `values` is a per-day array of COLUMNS_PER_DAY raw numbers (null = blank).
 */
function metricRow(key, values, extra = {}) {
  return {
    key,
    label: key,
    tone: null,
    ...extra,
    cells: values.flat().map((raw, index) => ({
      raw,
      display: raw == null ? '' : String(raw),
      day: `2026-07-${String(19 + Math.floor(index / COLUMNS_PER_DAY)).padStart(2, '0')}`,
      bucket: 'bucket',
      metric: key,
      editable: true,
    })),
  }
}

// Column order: uni_search, uni_shelves, manual_search, manual_catalog,
// manual_shelves, cpc_search, cpc_shelves, total, organic.
const ONLY_TOTAL = [null, null, null, null, null, null, null, 42, null]
const TOTAL_AND_ORGANIC = [null, null, null, null, null, null, null, 9, 9]
const WITH_CAMPAIGNS = [5, null, 3, null, null, 2, null, 9, 1]

describe('metricDayItems', () => {
  it('takes «Общая» as the headline value of the requested day', () => {
    const rows = [metricRow('orders', [ONLY_TOTAL, TOTAL_AND_ORGANIC])]

    const [item] = metricDayItems(rows, 1)

    expect(item.cell.raw).toBe(9)
  })

  it('offers no breakdown when only «Общая» carries a value', () => {
    const rows = [metricRow('orders', [ONLY_TOTAL])]

    const [item] = metricDayItems(rows, 0)

    // A split that restates the headline is noise, not information.
    expect(item.breakdown).toBeNull()
  })

  it('offers a breakdown as soon as any other column carries a value', () => {
    const rows = [metricRow('orders', [TOTAL_AND_ORGANIC])]

    const [item] = metricDayItems(rows, 0)

    expect(item.breakdown).toHaveLength(COLUMNS_PER_DAY)
    expect(item.breakdown.map((entry) => entry.label)).toEqual([
      'Единая ставка · Поиск',
      'Единая ставка · Полки',
      'Руч. поиск · Поиск',
      'Руч. поиск · Каталог',
      'Руч. полки · Полки',
      'CPC · Поиск',
      'CPC · Полки',
      'Общая',
      'Органика',
    ])
    expect(item.breakdown.at(-1).cell.raw).toBe(9)
  })

  it('breaks «ДРР от продаж» down by campaign, not by zone', () => {
    // The value is campaign-level: one merged cell per traffic group, not per
    // leaf column — and the CPC group's value sits on its «Поиск» leg.
    const rows = [metricRow('drr_sales', [WITH_CAMPAIGNS])]

    const [item] = metricDayItems(rows, 0)

    expect(item.breakdown.map((entry) => entry.label)).toEqual([
      'Единая ставка',
      'Руч. поиск',
      'Руч. полки',
      'CPC',
      'Общая',
      'Органика',
    ])
    expect(item.breakdown.find((entry) => entry.label === 'CPC').cell.raw).toBe(2)
  })

  it('gives «Процент выкупа» no breakdown at all', () => {
    // One number for the whole day — a SKU-level cohort, not a per-zone fact.
    const rows = [metricRow('buyout_percent', [WITH_CAMPAIGNS])]

    const [item] = metricDayItems(rows, 0)

    expect(item.cell.raw).toBe(9)
    expect(item.breakdown).toBeNull()
  })
})

describe('blockDayItems', () => {
  it('indexes «Цены»/«Остатки» rows by day, not by traffic column', () => {
    const rows = [
      {
        key: 'seller_price',
        label: 'Цена продавца, KGS',
        cells: [{ raw: 2900 }, { raw: 3100 }],
      },
    ]

    expect(blockDayItems(rows, 1)[0].cell.raw).toBe(3100)
    expect(blockDayItems(rows, 1)[0].breakdown).toBeNull()
  })
})

describe('dayLabelWithWeekday', () => {
  it('appends the local weekday', () => {
    expect(dayLabelWithWeekday({ iso: '2026-07-19', label: '19.07.2026' })).toBe('19.07.2026 (вс)')
  })

  it('reads the ISO parts as a LOCAL date', () => {
    // `new Date('2026-07-19')` parses as UTC and lands on the 18th west of
    // Greenwich — which would label every day with the wrong weekday there.
    expect(dayLabelWithWeekday({ iso: '2026-07-20', label: '20.07.2026' })).toBe('20.07.2026 (пн)')
  })
})
