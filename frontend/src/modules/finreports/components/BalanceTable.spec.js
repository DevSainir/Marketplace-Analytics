import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import BalanceTable from '@/modules/finreports/components/BalanceTable.vue'

// Groups ask the server for their list on mount; these tables need none.
vi.mock('@/modules/heatmap/api', () => ({ fetchGroups: vi.fn(async () => ({ items: [] })) }))

beforeEach(() => setActivePinia(createPinia()))

/**
 * The balance grid is FOUR separate blocks, and only one of them scrolls. That
 * split is what fixed the clipped panel and the phantom scrollbar, but it moved
 * the alignment out of the browser's hands and into ours: nothing but the sync
 * keeps "SKU total" against its row and "Warehouse total" under its
 * column. A broken listener would not throw — the totals would simply describe
 * the wrong rows, which is the worst way for a balance sheet to fail.
 */
const PAYLOAD = {
  stat_date: '2026-08-03',
  currency: 'KGS',
  rows: [
    {
      nm_id: 953770957,
      sa_name: 'm-trx01-blk',
      subject_name: 'Trousers',
      brand_name: 'NORTH LINE',
      cost_price: '800',
      cells: [
        {
          warehouse_name: 'Tula',
          quantity: 72,
          in_way: 5,
          balance: '57600',
          in_way_balance: '4000',
        },
        {
          warehouse_name: 'Koledino',
          quantity: 8,
          in_way: 0,
          balance: '6400',
          in_way_balance: '0',
        },
      ],
    },
    {
      nm_id: 611450917,
      sa_name: 'm-wdx02-wht',
      subject_name: 'Shorts',
      brand_name: 'OTHER',
      cost_price: '300',
      cells: [
        { warehouse_name: 'Tula', quantity: 40, in_way: 0, balance: '12000', in_way_balance: '0' },
      ],
    },
  ],
  uncounted_warehouses: [],
  uncounted_skus: [],
  uncosted_count: 0,
  notes: [],
}

function mountTable() {
  const wrapper = mount(BalanceTable, {
    props: { balance: PAYLOAD },
    attachTo: document.body,
  })
  return {
    wrapper,
    grid: wrapper.find('.grid-scroll').element,
    rowTotals: wrapper.findAll('.totals-scroll')[0].element,
    columnTotals: wrapper.findAll('.totals-scroll')[1].element,
  }
}

describe('BalanceTable', () => {
  it('carries the grid’s vertical offset to the row-totals block', async () => {
    const { grid, rowTotals } = mountTable()

    grid.scrollTop = 240
    await grid.dispatchEvent(new Event('scroll'))

    expect(rowTotals.scrollTop).toBe(240)
  })

  it('carries the grid’s horizontal offset to the column-totals block', async () => {
    const { grid, columnTotals } = mountTable()

    grid.scrollLeft = 180
    await grid.dispatchEvent(new Event('scroll'))

    expect(columnTotals.scrollLeft).toBe(180)
  })

  it('scrolls the grid when the wheel turns over a panel', async () => {
    // The panels have no scrollbars of their own, so a wheel over "SKU
    // total" would otherwise do nothing and read as a frozen table.
    const { grid, rowTotals } = mountTable()

    rowTotals.dispatchEvent(new WheelEvent('wheel', { deltaY: 90, cancelable: true }))

    expect(grid.scrollTop).toBe(90)
    expect(rowTotals.scrollTop).toBe(90)
  })

  it('renders one panel row per grid row, in the same order', async () => {
    // Same count and same order is the other half of staying aligned: the two
    // blocks scroll as one, so a row missing from either shifts every total
    // below it onto the wrong SKU.
    const { wrapper, grid, rowTotals } = mountTable()

    const names = [...grid.querySelectorAll('tbody .sku-name')].map((n) => n.textContent.trim())
    const totals = [...rowTotals.querySelectorAll('tbody tr')].map((r) =>
      r.firstElementChild.textContent.trim(),
    )

    expect(names).toEqual(['M-TRX01-BLK', 'M-WDX02-WHT'])
    expect(totals).toEqual(['80', '40'])
    wrapper.unmount()
  })

  it('gives goods in transit their own column and folds them into the money', async () => {
    // "In transit" sits between the units and the money because it belongs to both:
    // outside "In stock", which is what can ship today, and inside "At cost
    // price", which is what the seller has already paid for.
    const { wrapper, rowTotals } = mountTable()

    const headers = [...rowTotals.querySelectorAll('thead tr:last-child th')].map((h) =>
      h.textContent.trim(),
    )
    const trousers = [...rowTotals.querySelectorAll('tbody tr')[0].children].map((c) =>
      c.textContent.trim(),
    )

    expect(headers).toEqual(['In stock', 'In transit', 'At cost price'])
    // 80 lying in the two warehouses, 5 in transit, and 64,000 + 4,000 of money.
    expect(trousers).toEqual(['80', '5', 'KGS 68,000'])
    // A SKU with nothing moving leaves the column blank — a column of zeros
    // down a catalog that mostly sits still buries the rows that move.
    expect([...rowTotals.querySelectorAll('tbody tr')[1].children][1].textContent.trim()).toBe('')
    wrapper.unmount()
  })

  it('keeps the grid and "Warehouse total" strictly about what is on the shelf', async () => {
    // Goods in transit are on no shelf, so they appear in neither — they are
    // counted once, in the row panel and the corner. A cell that quietly priced
    // them would make a warehouse look like it is holding stock it has not got.
    const { wrapper, grid, columnTotals } = mountTable()

    const tula = grid.querySelectorAll('tbody tr')[0].querySelectorAll('.cell-wh')[0]
    const shelfMoney = [...columnTotals.querySelectorAll('tbody tr')].map((r) =>
      r.children[1].textContent.trim(),
    )

    // 72 lying in Tula at 800 — the 5 in transit are not priced into the cell.
    expect(tula.textContent.replace(/\s+/g, ' ').trim()).toBe('72|KGS 57,600')
    expect(shelfMoney).toEqual(['112', 'KGS 69,600'])
    wrapper.unmount()
  })
})
