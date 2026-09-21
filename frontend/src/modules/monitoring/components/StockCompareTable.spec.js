import { mount } from '@vue/test-utils'

import StockCompareTable from '@/modules/monitoring/components/StockCompareTable.vue'

/**
 * The «Остатки по складам» ribbon: ONE table, one size column, a column group
 * per day of the period. What is pinned here is the part the pivot helpers
 * cannot see — that every group repeats the same warehouse columns in the same
 * order, so a row reads straight across the days.
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
  it('gives the width rule one day group per day', () => {
    // `--days` is what sizes a group at half the grid: two days on screen and
    // the rest of the period a sideways scroll away.
    const wrapper = mountTable([cell(1, 'S', 'Казань', 1)], [], [], [])

    expect(wrapper.find('.app-datatable').attributes('style')).toContain('--days: 4')
    expect(wrapper.findAll('thead tr')[0].findAll('th')).toHaveLength(5)
  })

  it('prints one size column for the period, not one per day', () => {
    const wrapper = mountTable([cell(1, 'S', 'Казань', 3)], [cell(1, 'S', 'Казань', 2)])

    expect(wrapper.findAll('table')).toHaveLength(1)
    expect(wrapper.findAll('thead th.col-size')).toHaveLength(1)
  })

  it('repeats the same warehouse columns under every day', () => {
    // «Тула» exists on the second day only; it still gets a column under the
    // first, or the two groups would stop lining up.
    const wrapper = mountTable([cell(1, 'S', 'Казань', 3)], [cell(1, 'S', 'Тула', 9)])

    const headers = wrapper.findAll('thead tr')[1].findAll('th')

    expect(headers.map((th) => th.text())).toEqual([
      'Всего',
      'Тула',
      'Казань',
      'Всего',
      'Тула',
      'Казань',
    ])
  })

  it('reads one size straight across both days', () => {
    const wrapper = mountTable(
      [cell(1, 'S', 'Казань', 3), cell(2, 'M', 'Казань', 10)],
      [cell(1, 'S', 'Казань', 2)],
    )

    // размер | день 1: всего, Казань | день 2: всего, Казань
    expect(rowText(wrapper, 0)).toEqual(['S', '3', '3', '2', '2'])
    // «M» sold out overnight: the row stays, the second day is blank.
    expect(rowText(wrapper, 1)).toEqual(['M', '10', '10', '', ''])
  })

  it('totals each day in its own group', () => {
    const wrapper = mountTable(
      [cell(1, 'S', 'Казань', 3), cell(2, 'M', 'Тула', 10)],
      [cell(1, 'S', 'Казань', 2)],
    )

    const totals = wrapper.findAll('tfoot td').map((td) => td.text())

    expect(totals).toEqual(['Всего', '13', '10', '3', '2', '', '2'])
  })

  it('says so when neither day holds any stock', () => {
    const wrapper = mountTable([], [])

    expect(wrapper.find('table').exists()).toBe(false)
    expect(wrapper.text()).toContain('Нет складских остатков')
  })
})
