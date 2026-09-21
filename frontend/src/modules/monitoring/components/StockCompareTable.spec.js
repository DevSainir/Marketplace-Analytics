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

/** One argument per day, oldest first: that day's cells. */
function mountTable(...cellsPerDay) {
  return mount(StockCompareTable, {
    props: {
      days: cellsPerDay.map((cells, index) => ({
        key: `2026-07-1${index}`,
        label: `1${index}.07.2026`,
        cells,
      })),
      sizeOrder: SIZES,
    },
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
    const wrapper = mountTable([cell(1, 'S', 'Казань', 3)], [cell(1, 'S', 'Тула', 9)])

    const headers = wrapper.findAll('thead tr')[1].findAll('th')

    expect(headers.map((th) => th.text())).toEqual(['Всего', 'Казань', 'Всего', 'Тула'])
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
      undefined,
      'width: calc((var(--group-w) - var(--col-total-w)) / 1);',
      undefined,
      'width: calc((var(--group-w) - var(--col-total-w)) / 2);',
      'width: calc((var(--group-w) - var(--col-total-w)) / 2);',
    ])
  })

  it('reads one size across the days', () => {
    const wrapper = mountTable(
      [cell(1, 'S', 'Казань', 3), cell(2, 'M', 'Казань', 10)],
      [cell(1, 'S', 'Казань', 2)],
    )

    // размер | день 1: всего, Казань | день 2: всего, Казань
    expect(rowText(wrapper, 0)).toEqual(['S', '3', '3', '2', '2'])
    // «M» sold out overnight: the row stays, and the second day shows the gap.
    expect(rowText(wrapper, 1)).toEqual(['M', '10', '10', '', ''])
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

  it('says so when no day of the period holds any stock', () => {
    const wrapper = mountTable([], [])

    expect(wrapper.find('table').exists()).toBe(false)
    expect(wrapper.text()).toContain('Нет складских остатков')
  })
})
