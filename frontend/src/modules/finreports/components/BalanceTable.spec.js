import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import BalanceTable from '@/modules/finreports/components/BalanceTable.vue'

/**
 * The balance grid is FOUR separate blocks, and only one of them scrolls. That
 * split is what fixed the clipped panel and the phantom scrollbar, but it moved
 * the alignment out of the browser's hands and into ours: nothing but the sync
 * keeps «Итого по артикулу» against its row and «Итого по складу» under its
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
      subject_name: 'Брюки',
      brand_name: 'NORTH LINE',
      cost_price: '800',
      cells: [
        { warehouse_name: 'Тула', quantity: 72, balance: '57600' },
        { warehouse_name: 'Коледино', quantity: 8, balance: '6400' },
      ],
    },
    {
      nm_id: 611450917,
      sa_name: 'm-wdx02-wht',
      subject_name: 'Шорты',
      brand_name: 'OTHER',
      cost_price: '300',
      cells: [{ warehouse_name: 'Тула', quantity: 40, balance: '12000' }],
    },
  ],
  pinned_skus: [],
  pinned_warehouses: [],
  uncounted_warehouses: [],
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
    // The panels have no scrollbars of their own, so a wheel over «Итого по
    // артикулу» would otherwise do nothing and read as a frozen table.
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

    expect(names).toEqual(['m-trx01-blk', 'm-wdx02-wht'])
    expect(totals).toEqual(['80', '40'])
    wrapper.unmount()
  })
})
