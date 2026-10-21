import { mount } from '@vue/test-utils'

import StockCompareTable from '@/modules/monitoring/components/StockCompareTable.vue'

// jsdom has no ResizeObserver, and the grid observes its scroller on mount to
// measure one day group.
globalThis.ResizeObserver ??= class {
  observe() {}
  disconnect() {}
}

/**
 * The «Остатки по складам» ribbon: ONE table, one size column, a column group
 * per day of the period. What is pinned here is what the pivot helpers cannot
 * see — that a day carries only the warehouses it actually stocked, and that
 * the day groups stay the same width anyway.
 */
const cell = (chrt_id, tech_size, warehouse_name, quantity) => ({
  chrt_id,
  tech_size,
  warehouse_name,
  quantity,
})

const SIZES = [
  { chrt_id: 1, tech_size: 'S' },
  { chrt_id: 2, tech_size: 'M' },
]

/** jsdom lays nothing out, so the scroll container needs a width to measure. */
Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, value: 1232 })

/** The day props the grid takes, one entry per day of cells given. */
function dayProps(cellsPerDay) {
  return cellsPerDay.map((cells, index) => ({
    key: `2026-07-1${index}`,
    label: `1${index}.07.2026`,
    cells,
  }))
}

/** One argument per day, oldest first: that day's cells. */
function mountTable(...cellsPerDay) {
  return mount(StockCompareTable, {
    props: { days: dayProps(cellsPerDay), sizeOrder: SIZES },
    global: { stubs: { Teleport: true } },
  })
}

/** The cells of the body row for a given size, as plain text. */
function rowText(wrapper, index) {
  const row = wrapper.findAll('tbody tr')[index]
  return row.findAll('td').map((td) => td.text())
}

describe('StockCompareTable', () => {
  it('prints one size column for the period, not one per day', () => {
    const wrapper = mountTable([cell(1, 'S', 'Казань', 3)], [cell(1, 'S', 'Казань', 2)])

    expect(wrapper.findAll('table')).toHaveLength(1)
    expect(wrapper.findAll('thead th.col-size')).toHaveLength(1)
  })

  it('gives the width rule one day group per day', () => {
    // `--days` is what sizes a group at half the grid: two days on screen and
    // the rest of the period a sideways scroll away.
    const wrapper = mountTable([cell(1, 'S', 'Казань', 1)], [], [], [])

    expect(wrapper.find('.app-datatable').attributes('style')).toContain('--days: 4')
    expect(wrapper.findAll('thead tr')[0].findAll('th')).toHaveLength(5)
  })

  it('gives each day only the warehouses it stocked', () => {
    // «Тула» holds stock on the second day only. Carrying it under the first as
    // a blank column is what a quarter-long period turns into dozens of.
    const wrapper = mountTable(
      [cell(1, 'S', 'Казань', 3), cell(2, 'M', 'Коледино', 1)],
      [cell(1, 'S', 'Тула', 9)],
    )

    const headers = wrapper.findAll('thead tr')[1].findAll('th')

    expect(headers.map((th) => th.text())).toEqual(['Всего', 'Казань', 'Коледино', 'Всего', 'Тула'])
  })

  it('splits a day group between the warehouses of that day', () => {
    // Days hold different numbers of columns; the colgroup is what keeps both
    // groups the same width anyway (see the component).
    const wrapper = mountTable(
      [cell(1, 'S', 'Казань', 3)],
      [cell(1, 'S', 'Тула', 9), cell(2, 'M', 'Казань', 4)],
    )

    const widths = wrapper.findAll('colgroup col').map((col) => col.attributes('style'))

    expect(widths).toEqual([
      undefined,
      'width: var(--col-total-w);',
      'width: calc((var(--group-w) - var(--col-total-w)) / 1);',
      'width: var(--col-total-w);',
      'width: calc((var(--group-w) - var(--col-total-w)) / 2);',
      'width: calc((var(--group-w) - var(--col-total-w)) / 2);',
    ])
  })

  it('reads one size across the days', () => {
    const wrapper = mountTable(
      [cell(1, 'S', 'Казань', 3), cell(2, 'M', 'Казань', 10), cell(2, 'M', 'Тула', 1)],
      [cell(1, 'S', 'Казань', 2)],
    )

    // size | day 1: total, Казань, Тула | day 2: total, Казань
    expect(rowText(wrapper, 0)).toEqual(['S', '3', '3', '', '2', '2'])
    // «M» sold out overnight: the row stays, and the second day shows the gap.
    expect(rowText(wrapper, 1)).toEqual(['M', '11', '10', '1', '', ''])
  })

  it('totals each day in its own group', () => {
    const wrapper = mountTable(
      [cell(1, 'S', 'Казань', 3), cell(2, 'M', 'Тула', 10)],
      [cell(1, 'S', 'Казань', 2)],
    )

    // Each day's «Всего» is the sum of the columns beside it — no other day's
    // warehouse is hiding in it as a blank.
    expect(wrapper.findAll('tfoot td').map((td) => td.text())).toEqual([
      'Всего',
      '13',
      '10',
      '3',
      '2',
      '2',
    ])
  })

  it('measures a day group once the stock arrives, not only at mount', async () => {
    // The stock comes in its own request, so at mount there is no grid to
    // measure yet. Measuring only there left `--group-w` at zero — and the
    // colgroup divides that between the day's warehouses, so every warehouse
    // column collapsed and the grid became a row of «Всего».
    const wrapper = mountTable()

    expect(wrapper.attributes('style')).not.toContain('--group-w')

    await wrapper.setProps({
      days: dayProps([
        [cell(1, 'S', 'Казань', 3), cell(1, 'S', 'Тула', 1)],
        [cell(1, 'S', 'Казань', 2)],
      ]),
    })
    await wrapper.vm.$nextTick()

    // (1232 - the size column) / 2 — the size column measures 0 in jsdom, which
    // has no stylesheet to read it from.
    expect(wrapper.attributes('style')).toContain('--group-w: 616px')
  })

  it('gives a one-day period the whole width, not half of it', async () => {
    // Sized for two days a screen, a single day left the right half of the card
    // empty.
    const wrapper = mountTable([cell(1, 'S', 'Казань', 3), cell(1, 'S', 'Тула', 1)])
    await wrapper.vm.$nextTick()

    // 1232 / 1 — the size column measures 0 in jsdom.
    expect(wrapper.attributes('style')).toContain('--group-w: 1232px')
  })

  describe('a seller with one warehouse', () => {
    // Every day runs off at most one warehouse (a seller with a single WB warehouse). «Всего»
    // would only repeat that column, and two one-column days across the screen
    // are two numbers with a gulf between them.
    const oneWarehouse = () =>
      mountTable([cell(1, 'S', 'Казань', 3)], [], [cell(1, 'S', 'Казань', 2)])

    it('drops «Всего» and keeps an empty day as a blank column', () => {
      const wrapper = oneWarehouse()

      const headers = wrapper.findAll('thead tr')[1].findAll('th')

      expect(headers.map((th) => th.text())).toEqual(['Казань', '', 'Казань'])
      expect(rowText(wrapper, 0)).toEqual(['S', '3', '', '2'])
    })

    it('fits five days a screen instead of two', async () => {
      const wrapper = oneWarehouse()
      await wrapper.vm.$nextTick()

      // 1232 / 5 — the size column measures 0 in jsdom.
      expect(wrapper.attributes('style')).toContain('--group-w: 246.4px')
    })
  })

  it('says so when no day of the period holds any stock', () => {
    const wrapper = mountTable([], [])

    expect(wrapper.find('table').exists()).toBe(false)
    expect(wrapper.text()).toContain('Нет складских остатков')
  })
})
