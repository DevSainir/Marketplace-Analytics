import { formatCurrency, formatCurrencyTenths, formatNumber } from '@/core/utils/format'
import {
  COLUMNS_PER_DAY,
  DRR_SALES_COLUMNS,
  TRAFFIC_COLUMNS,
  TRAFFIC_GROUPS,
  buildMetricsMatrix,
  patchMetricsMatrix,
} from '@/modules/monitoring/metricsMatrix'

describe('traffic column structure', () => {
  it('has one leaf column per workbook zone, CPC included', () => {
    expect(TRAFFIC_COLUMNS.map((c) => c.zone)).toEqual([
      'Поиск',
      'Полки',
      'Каталог',
      'Поиск',
      'Каталог',
      'Полки',
      'Поиск',
      'Полки',
      'Общая',
      'Органика',
    ])
  })

  it('gives the CPC group its own Поиск/Полки pair', () => {
    const cpc = TRAFFIC_GROUPS.find((g) => g.label === 'CPC')
    const offset = TRAFFIC_GROUPS.slice(0, TRAFFIC_GROUPS.indexOf(cpc)).reduce(
      (sum, g) => sum + g.span,
      0,
    )

    expect(TRAFFIC_COLUMNS.slice(offset, offset + cpc.span).map((c) => c.key)).toEqual([
      'cpc_search',
      'cpc_shelves',
    ])
  })

  it('group spans cover exactly the leaf columns', () => {
    const spanned = TRAFFIC_GROUPS.reduce((sum, g) => sum + g.span, 0)
    expect(spanned).toBe(TRAFFIC_COLUMNS.length)
  })

  it('merges «ДРР от продаж» into exactly one cell per traffic group', () => {
    // The row's day/group dividers are drawn by an `nth-child(6n + …)` cadence
    // in MatrixMetricsRows.css, and 6 is this length — the row merges its
    // zones, so it lays out fewer cells per day than the rows above and cannot
    // inherit their cadence. Adding a traffic group without an entry here (or
    // vice versa) slides every divider on this row out of line with the table,
    // which is what happened when the CPC group landed.
    expect(DRR_SALES_COLUMNS).toHaveLength(TRAFFIC_GROUPS.length)
    expect(DRR_SALES_COLUMNS.map((c) => c.span)).toEqual(TRAFFIC_GROUPS.map((g) => g.span))

    // ...and those cells tile the day exactly: each starts where the last ended.
    const offsets = DRR_SALES_COLUMNS.map((c) => c.offset)
    let running = 0
    for (const [index, column] of DRR_SALES_COLUMNS.entries()) {
      expect(offsets[index]).toBe(running)
      expect(TRAFFIC_COLUMNS[column.offset].key).toBe(column.key)
      running += column.span
    }
    expect(running).toBe(COLUMNS_PER_DAY)
  })
})

// The backend matrix uses the same bucket order as TRAFFIC_COLUMNS; cells are
// raw numbers (or null -> blank). Day-major flat: values[day * buckets + bucket].
const BUCKETS = TRAFFIC_COLUMNS.map((c) => c.key)

/** Build one backend row from per-day bucket maps ({} = all-null day). */
function backendRow(key, days) {
  return {
    key,
    values: days.flatMap((byBucket) => BUCKETS.map((b) => byBucket[b] ?? null)),
  }
}

const PRODUCT = {
  nm_id: 1,
  window: { start: '2026-07-01', end: '2026-07-02' },
  matrix: {
    days: ['2026-07-01', '2026-07-02'],
    buckets: BUCKETS,
    rows: [
      backendRow('traffic_share', [
        { uni_search: 20, uni_shelves: 46.67, manual_search: 26.67 },
        {},
      ]),
      backendRow('spend', [{ uni_search: 15, uni_shelves: 35, manual_search: 20, total: 75 }, {}]),
      backendRow('views', [
        { uni_search: 30, uni_shelves: 70, manual_search: 40, cpc_search: 25, total: 150 },
        {},
      ]),
      backendRow('ctr', [{ uni_search: 10, manual_search: 10 }, {}]),
      backendRow('cpc', [{ cpc_search: 12.5, cpc_shelves: 9.4 }, {}]),
      backendRow('clicks', [{ uni_search: 3, total: 200, organic: 185 }, {}]),
      backendRow('order_sum', [{ manual_search: 500, total: 5000 }, {}]),
      backendRow('buyout_percent', [{ total: 50 }, { total: 50 }]),
      backendRow('seller_price', [{ total: 1000 }, {}]),
      backendRow('customer_price', [{ total: 700 }, {}]),
      backendRow('spp', [{ total: 30 }, {}]),
    ],
  },
}

const COLS = TRAFFIC_COLUMNS.length
const col = (key) => TRAFFIC_COLUMNS.findIndex((c) => c.key === key)

/** Cell object for metric `rowKey` on day index `d` in traffic column `colKey`. */
function cellObj(matrix, rowKey, d, colKey) {
  return matrix.rows.find((r) => r.key === rowKey).cells[d * COLS + col(colKey)]
}

/** Formatted display string of that cell. */
function cell(matrix, rowKey, d, colKey) {
  return cellObj(matrix, rowKey, d, colKey).display
}

/** Cell of a day-bound block row (priceRows/stockRows): one cell per day. */
function blockCell(rows, rowKey, d) {
  return rows.find((r) => r.key === rowKey).cells[d]
}

describe('buildMetricsMatrix', () => {
  it('spans the whole window with full-date section labels, 7 cells per day', () => {
    const matrix = buildMetricsMatrix(PRODUCT)
    expect(matrix.days.map((d) => d.label)).toEqual(['01.07.2026', '02.07.2026'])
    for (const row of matrix.rows) expect(row.cells).toHaveLength(2 * COLS)
  })

  it('marks EVERY cell editable (invertible inputs + display-override cells)', () => {
    const matrix = buildMetricsMatrix(PRODUCT)
    // Invertible inputs and derived cells alike are clickable…
    expect(cellObj(matrix, 'views', 0, 'uni_search').editable).toBe(true)
    expect(cellObj(matrix, 'traffic_share', 0, 'uni_search').editable).toBe(true)
    expect(cellObj(matrix, 'clicks', 0, 'total').editable).toBe(true)
    // …including the former read-only cells: a rollup, the empty «Каталог», organic.
    expect(cellObj(matrix, 'spend', 0, 'total').editable).toBe(true)
    expect(cellObj(matrix, 'clicks', 0, 'organic').editable).toBe(true)
    expect(cellObj(matrix, 'views', 0, 'uni_catalog').editable).toBe(true)
    // …and blank cells too (fill-in).
    expect(cellObj(matrix, 'views', 0, 'manual_shelves').editable).toBe(true)
  })

  it('makes every block cell editable (prices, СПП, and stock)', () => {
    // Prices live in the day-bound «Цены» block (one «Общая» cell per day).
    const matrix = buildMetricsMatrix(PRODUCT)
    expect(blockCell(matrix.priceRows, 'seller_price', 0).editable).toBe(true)
    expect(blockCell(matrix.priceRows, 'customer_price', 0).editable).toBe(true)
    // СПП is derived but still editable (display override); its value still shows.
    expect(blockCell(matrix.priceRows, 'spp', 0).editable).toBe(true)
    expect(blockCell(matrix.priceRows, 'spp', 0).display).toBe('30,00%')
    // Block cells address the backend «total» bucket for edits.
    expect(blockCell(matrix.priceRows, 'seller_price', 0)).toMatchObject({
      raw: 1000,
      day: '2026-07-01',
      bucket: 'total',
      metric: 'seller_price',
    })
    // A gap day renders blank but is clickable (fill in a missing price).
    expect(blockCell(matrix.priceRows, 'seller_price', 1).display).toBe('')
    expect(blockCell(matrix.priceRows, 'seller_price', 1).editable).toBe(true)
  })

  it('carries the raw numeric value and addressing for editing', () => {
    const matrix = buildMetricsMatrix(PRODUCT)
    const c = cellObj(matrix, 'views', 0, 'uni_search')
    expect(c).toMatchObject({ raw: 30, day: '2026-07-01', bucket: 'uni_search', metric: 'views' })
  })

  it('keeps the workbook row order (prices/stock split into blocks)', () => {
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
    expect(matrix.priceRows.map((r) => r.key)).toEqual(['seller_price', 'customer_price', 'spp'])
    expect(matrix.stockRows.map((r) => r.key)).toEqual([
      'stock_quantity',
      'stock_to_client',
      'stock_from_client',
    ])
  })

  it('renders stock block rows with their value (now editable via override)', () => {
    const stocked = structuredClone(PRODUCT)
    stocked.matrix.rows.push(backendRow('stock_quantity', [{ total: 42 }, { total: 42 }]))
    const matrix = buildMetricsMatrix(stocked)
    const c = blockCell(matrix.stockRows, 'stock_quantity', 0)
    expect(c.display).toBe(formatNumber(42))
    expect(c.editable).toBe(true)
  })

  it('formats backend numbers per metric kind (currency/number/percent)', () => {
    const matrix = buildMetricsMatrix(PRODUCT)
    expect(cell(matrix, 'spend', 0, 'total')).toBe(formatCurrency(75))
    expect(cell(matrix, 'views', 0, 'total')).toBe(formatNumber(150))
    expect(cell(matrix, 'clicks', 0, 'total')).toBe(formatNumber(200))
    expect(cell(matrix, 'traffic_share', 0, 'uni_shelves')).toBe('46,67%')
    expect(cell(matrix, 'buyout_percent', 0, 'total')).toBe('50,00%')
    expect(cell(matrix, 'order_sum', 0, 'manual_search')).toBe(formatCurrency(500))
  })

  it('lays out per-type/zone cells from the backend buckets', () => {
    const matrix = buildMetricsMatrix(PRODUCT)
    expect(cell(matrix, 'views', 0, 'uni_search')).toBe(formatNumber(30))
    expect(cell(matrix, 'views', 0, 'uni_shelves')).toBe(formatNumber(70))
    expect(cell(matrix, 'views', 0, 'manual_search')).toBe(formatNumber(40))
    expect(cell(matrix, 'clicks', 0, 'organic')).toBe(formatNumber(185))
  })

  it('lands the CPC buckets in their own two columns', () => {
    const matrix = buildMetricsMatrix(PRODUCT)

    // A pay-per-click campaign's ставка is the CPC row itself, so the two zone
    // cells must address cpc_search/cpc_shelves and nothing beside them.
    // «CPC, ₽» prints tenths (formatCurrencyTenths) — a click costs single ₽.
    expect(cell(matrix, 'cpc', 0, 'cpc_search')).toBe(formatCurrencyTenths(12.5))
    expect(cell(matrix, 'cpc', 0, 'cpc_shelves')).toBe(formatCurrencyTenths(9.4))
    expect(cell(matrix, 'cpc', 0, 'uni_search')).toBe('')
    expect(cellObj(matrix, 'views', 0, 'cpc_search')).toMatchObject({
      raw: 25,
      bucket: 'cpc_search',
    })
  })

  it('renders blank for null cells, absent rows, and the legacy «Каталог» zone', () => {
    const matrix = buildMetricsMatrix(PRODUCT)
    expect(cell(matrix, 'views', 0, 'uni_catalog')).toBe('')
    expect(cell(matrix, 'views', 0, 'manual_shelves')).toBe('')
    expect(cell(matrix, 'traffic_share', 0, 'total')).toBe('')
    // Metric row missing from the payload entirely -> a full row of dashes.
    expect(cell(matrix, 'cpm', 0, 'total')).toBe('')
  })

  it('renders blank for gap days instead of errors', () => {
    const matrix = buildMetricsMatrix(PRODUCT)
    expect(cell(matrix, 'spend', 1, 'total')).toBe('')
    expect(cell(matrix, 'clicks', 1, 'total')).toBe('')
    expect(cell(matrix, 'clicks', 1, 'organic')).toBe('')
  })

  it('returns an empty matrix without a backend matrix payload', () => {
    const empty = { days: [], rows: [], priceRows: [], stockRows: [], stockTotalRows: [] }
    expect(buildMetricsMatrix(null)).toEqual(empty)
    expect(buildMetricsMatrix({ nm_id: 1 })).toEqual(empty)
  })
})

describe('patchMetricsMatrix', () => {
  /** A second product with a changed uni_search views value on day 0. */
  function editedProduct() {
    const clone = structuredClone(PRODUCT)
    const viewsRow = clone.matrix.rows.find((r) => r.key === 'views')
    viewsRow.values[BUCKETS.indexOf('uni_search')] = 999 // day 0, uni_search
    return clone
  }

  it('mutates changed cells in place without replacing objects', () => {
    const view = buildMetricsMatrix(PRODUCT)
    const viewsRow = view.rows.find((r) => r.key === 'views')
    const targetCell = viewsRow.cells[col('uni_search')]
    const untouchedCell = viewsRow.cells[col('manual_search')]
    const rowsRef = view.rows
    const cellRef = targetCell

    const patched = patchMetricsMatrix(view, editedProduct())

    expect(patched).toBe(true)
    expect(view.rows).toBe(rowsRef) // same array identity (no full rebuild)
    expect(viewsRow.cells[col('uni_search')]).toBe(cellRef) // same cell object
    expect(cellRef.raw).toBe(999)
    expect(cellRef.display).toBe(formatNumber(999))
    expect(untouchedCell.raw).toBe(40) // unchanged (manual_search views)
  })

  it('signals a rebuild when the day count differs', () => {
    const view = buildMetricsMatrix(PRODUCT)
    const oneDay = structuredClone(PRODUCT)
    oneDay.matrix.days = ['2026-07-01']
    expect(patchMetricsMatrix(view, oneDay)).toBe(false)
  })
})

// A carts/orders cell is the кампания's own count («ассоциированные конверсии»
// included); the card's share and the per-variant rows behind the hover ride
// alongside it.
describe('associative conversions', () => {
  /**
   * PRODUCT + a carts row (the campaign's 120), the viewed card's share of it
   * (82), and the per-variant breakdown on day 0 — the remaining 38 carts went
   * to two sibling variants.
   */
  function assocProduct({ exact = true } = {}) {
    const clone = structuredClone(PRODUCT)
    clone.matrix.rows.push(backendRow('carts', [{ uni_shelves: 120, manual_search: 8 }, {}]))
    clone.matrix.rows.push(backendRow('carts_sku', [{ uni_shelves: 82 }, {}]))
    clone.matrix_base = {
      days: [
        {
          day: '2026-07-01',
          buckets: {
            uni_shelves: {
              assoc_exact: exact,
              assoc_skus: [
                // nm_id 1 is PRODUCT.nm_id — the SKU on screen.
                { nm_id: 1, vendor_code: 'M-VIEWED', add_to_cart: 82, orders: 9 },
                { nm_id: 2, vendor_code: 'M-SIBLING', add_to_cart: 30, orders: 4 },
                { nm_id: 3, vendor_code: 'M-OTHER', add_to_cart: 8, orders: 1 },
              ],
            },
          },
        },
        { day: '2026-07-02', buckets: {} },
      ],
    }
    return clone
  }

  it('shows the campaign’s count alone — no «120(82)» parenthesis', () => {
    const matrix = buildMetricsMatrix(assocProduct())
    expect(cell(matrix, 'carts', 0, 'uni_shelves')).toBe(formatNumber(120))
  })

  // The inline editor seeds itself from `raw` and the backend's ₽ rows divide
  // the same count, so `raw` is the number the cell prints — never the card's
  // share, which would open a cell reading 120 on a draft of 82.
  it('carries the campaign’s count as the cell’s editable value', () => {
    const matrix = buildMetricsMatrix(assocProduct())
    expect(cellObj(matrix, 'carts', 0, 'uni_shelves').raw).toBe(120)
    expect(cellObj(matrix, 'carts', 0, 'manual_search').raw).toBe(8)
  })

  it('reports the associated share, not the cell total again', () => {
    const { assoc } = cellObj(buildMetricsMatrix(assocProduct()), 'carts', 0, 'uni_shelves')

    // The cell shows 120, of which 82 are this SKU's own -> 38 are associated.
    expect(assoc.associated).toBe(38)
    expect(assoc.exact).toBe(true)
  })

  it('lists every variant, flagging the one on screen', () => {
    const { assoc } = cellObj(buildMetricsMatrix(assocProduct()), 'carts', 0, 'uni_shelves')

    expect(assoc.skus).toEqual([
      { nm_id: 1, vendor_code: 'M-VIEWED', count: 82, isViewed: true },
      { nm_id: 2, vendor_code: 'M-SIBLING', count: 30, isViewed: false },
      { nm_id: 3, vendor_code: 'M-OTHER', count: 8, isViewed: false },
    ])
    // All the rows account for the cell; the unflagged ones for the associated
    // share the hover reports above them.
    expect(assoc.skus.reduce((sum, s) => sum + s.count, 0)).toBe(120)
    const others = assoc.skus.filter((s) => !s.isViewed)
    expect(others.reduce((sum, s) => sum + s.count, 0)).toBe(assoc.associated)
  })

  it('picks each metric its own counts out of the shared variant rows', () => {
    const matrix = buildMetricsMatrix(assocProduct())
    // No orders_sku row -> the orders cell has no gap to break down.
    expect(cellObj(matrix, 'orders', 0, 'uni_shelves').assoc).toBeNull()
    expect(cellObj(matrix, 'carts', 0, 'uni_shelves').assoc.skus.map((s) => s.count)).toEqual([
      82, 30, 8,
    ])
  })

  it('flags an apportioned breakdown so the hover can caption it', () => {
    const matrix = buildMetricsMatrix(assocProduct({ exact: false }))
    expect(cellObj(matrix, 'carts', 0, 'uni_shelves').assoc.exact).toBe(false)
  })

  it('leaves cells without an associative gap unhoverable', () => {
    const matrix = buildMetricsMatrix(assocProduct())
    expect(cellObj(matrix, 'carts', 0, 'manual_search').assoc).toBeNull()
    expect(cellObj(matrix, 'clicks', 0, 'uni_shelves').assoc).toBeNull()
  })

  it('moves the associated share when the SKU’s own slice is edited', () => {
    const view = buildMetricsMatrix(assocProduct())
    const edited = assocProduct()
    edited.matrix.rows.find((r) => r.key === 'carts_sku').values[col('uni_shelves')] = 100

    expect(patchMetricsMatrix(view, edited)).toBe(true)
    expect(cellObj(view, 'carts', 0, 'uni_shelves').assoc.associated).toBe(20)
  })

  // The per-variant rows live on the BASE, not the matrix, so a patch that
  // carries only the recomputed matrix silently empties every hover. Callers
  // (the store's edit/undo/redo path) must pass the new base along with it.
  it('keeps the variant rows when patched with the edited base', () => {
    const view = buildMetricsMatrix(assocProduct())
    // What the backend returns after the SKU's own carts are edited to 100:
    // the cell, the all-variant total and the viewed SKU's row all move.
    const edited = assocProduct()
    edited.matrix.rows.find((r) => r.key === 'carts_sku').values[col('uni_shelves')] = 100
    edited.matrix.rows.find((r) => r.key === 'carts').values[col('uni_shelves')] = 138
    edited.matrix_base.days[0].buckets.uni_shelves.assoc_skus[0].add_to_cart = 100

    expect(patchMetricsMatrix(view, edited)).toBe(true)

    const { assoc } = cellObj(view, 'carts', 0, 'uni_shelves')
    expect(assoc.skus.map((s) => s.nm_id)).toEqual([1, 2, 3])
    expect(assoc.skus.find((s) => s.isViewed).count).toBe(100)
  })

  it('empties the hover when the base is left out of the patch', () => {
    const view = buildMetricsMatrix(assocProduct())
    const withoutBase = assocProduct()
    delete withoutBase.matrix_base

    expect(patchMetricsMatrix(view, withoutBase)).toBe(true)
    expect(cellObj(view, 'carts', 0, 'uni_shelves').assoc.skus).toEqual([])
  })
})
