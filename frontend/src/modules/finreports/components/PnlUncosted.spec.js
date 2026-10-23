import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import PrimeVue from 'primevue/config'
import { beforeEach, vi } from 'vitest'

import PnlSkuTable from '@/modules/finreports/components/PnlSkuTable.vue'

// Groups ask the server for their list on mount; these tables need none.
vi.mock('@/modules/heatmap/api', () => ({ fetchGroups: vi.fn(async () => ({ items: [] })) }))

beforeEach(() => setActivePinia(createPinia()))

/** The fields of a backend `PnlSkuRow` these tests read; the rest default to zero. */
function row(overrides = {}) {
  return {
    nm_id: 953770957,
    sa_name: 'm-trx01-blk',
    subject_name: 'Trousers',
    brand_name: 'NORTH LINE',
    is_excluded: false,
    sold_units: 10,
    returned_units: 0,
    revenue_seller_price: '10000.00',
    revenue_paid: '8000.00',
    logistics_total: '1000.00',
    penalties_total: '0',
    penalties: [],
    cost_price: '500.00',
    cogs: '5000.00',
    payout_net: '7000.00',
    net_profit: '2000.00',
    ...overrides,
  }
}

const COSTED = row()
const UNCOSTED = row({
  nm_id: 111,
  sa_name: 'no-cost',
  cost_price: null,
  cogs: null,
  net_profit: null,
})

function mountTable(props = {}) {
  return mount(PnlSkuTable, {
    attachTo: document.body,
    props: { rows: [COSTED, UNCOSTED], unallocated: null, sizes: {}, currency: 'KGS', ...props },
    global: { plugins: [PrimeVue] },
  })
}

/** Rows of the desktop table, by their article. */
const tableRow = (wrapper, name) =>
  wrapper.findAll('tbody tr').find((tr) => tr.text().includes(name.toUpperCase()))

describe('articles with no cost price in the P&L', () => {
  it('marks only the uncosted article, in the frozen column', () => {
    const wrapper = mountTable()

    expect(tableRow(wrapper, 'no-cost').text()).toContain('no cost price')
    expect(tableRow(wrapper, 'm-trx01-blk').text()).not.toContain('no cost price')
    wrapper.unmount()
  })

  it('does not mark an article that sold nothing — its cost changes no figure', () => {
    const idle = row({ nm_id: 222, sa_name: 'idle', sold_units: 0, cost_price: null, cogs: null })
    const wrapper = mountTable({ rows: [idle] })

    expect(wrapper.text()).not.toContain('no cost price')
    wrapper.unmount()
  })

  it('says "missing" in the "Cost price" column rather than a dash', () => {
    const wrapper = mountTable({ rows: [UNCOSTED] })

    const cells = tableRow(wrapper, 'no-cost')
      .findAll('td')
      .map((td) => td.text())
    expect(cells).toContain('missing')
    wrapper.unmount()
  })

  it('"No cost price" leaves only those articles', async () => {
    const wrapper = mountTable()

    await wrapper.find('[data-testid="uncosted-filter"]').trigger('click')

    expect(tableRow(wrapper, 'no-cost')).toBeTruthy()
    expect(tableRow(wrapper, 'm-trx01-blk')).toBeUndefined()
    expect(wrapper.emitted('update:uncostedOnly').at(-1)).toEqual([true])
    wrapper.unmount()
  })

  it('leaves the dashboard cards on the whole window under "No cost price"', async () => {
    const wrapper = mountTable()

    await wrapper.find('[data-testid="uncosted-filter"]').trigger('click')

    // `null` is "show the backend dashboard": the filter is a to-do list over
    // the table, and the cards must not turn into one article's figures.
    expect(wrapper.emitted('dashboard-change').at(-1)).toEqual([null])
    wrapper.unmount()
  })

  it('still sums the cards over a search, without the uncosted filter narrowing them', async () => {
    const wrapper = mountTable({ uncostedOnly: true })

    await wrapper.find('input[type="search"]').setValue('trousers')

    const [subset] = wrapper.emitted('dashboard-change').at(-1)
    expect(subset.sold_units).toBe(20)
    wrapper.unmount()
  })

  it('offers no such filter when every article has a cost', () => {
    const wrapper = mountTable({ rows: [COSTED] })

    expect(wrapper.find('[data-testid="uncosted-filter"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('drops the filter once the last article gets its cost', async () => {
    const wrapper = mountTable({ uncostedOnly: true })

    await wrapper.setProps({ rows: [COSTED, { ...UNCOSTED, cost_price: '300.00' }] })

    expect(wrapper.emitted('update:uncostedOnly').at(-1)).toEqual([false])
    wrapper.unmount()
  })

  it('saves the typed cost through the page and closes the dialog', async () => {
    const saveCost = vi.fn(async () => {})
    const wrapper = mountTable({ saveCost })

    await tableRow(wrapper, 'no-cost').find('[data-testid="enter-cost"]').trigger('click')
    const input = document.querySelector('#pnl-cost-input')
    input.value = '795,50'
    input.dispatchEvent(new Event('input'))
    document.querySelector('#pnl-cost-form').dispatchEvent(new Event('submit'))
    await flushPromises()

    expect(saveCost).toHaveBeenCalledWith({ nmId: 111, cost: 795.5, vendorCode: 'no-cost' })
    expect(document.querySelector('[data-testid="cost-dialog"]')).toBeNull()
    wrapper.unmount()
  })

  it('keeps the dialog open and says why when the save is refused', async () => {
    const saveCost = vi.fn(async () => {
      throw new Error('Server unavailable')
    })
    const wrapper = mountTable({ saveCost })

    await tableRow(wrapper, 'no-cost').find('[data-testid="enter-cost"]').trigger('click')
    const input = document.querySelector('#pnl-cost-input')
    input.value = '700'
    input.dispatchEvent(new Event('input'))
    document.querySelector('#pnl-cost-form').dispatchEvent(new Event('submit'))
    await flushPromises()

    expect(document.querySelector('[data-testid="cost-dialog"]').textContent).toContain(
      'Server unavailable',
    )
    wrapper.unmount()
  })

  it('refuses a negative cost before asking the server', async () => {
    const saveCost = vi.fn(async () => {})
    const wrapper = mountTable({ saveCost })

    await tableRow(wrapper, 'no-cost').find('[data-testid="enter-cost"]').trigger('click')
    const input = document.querySelector('#pnl-cost-input')
    input.value = '-5'
    input.dispatchEvent(new Event('input'))
    document.querySelector('#pnl-cost-form').dispatchEvent(new Event('submit'))
    await flushPromises()

    expect(saveCost).not.toHaveBeenCalled()
    expect(document.querySelector('[data-testid="cost-dialog"]').textContent).toContain(
      'A number from 0',
    )
    wrapper.unmount()
  })

  it('shows a read-only member the mark but offers no entry', () => {
    const wrapper = mountTable({ saveCost: null })

    expect(tableRow(wrapper, 'no-cost').text()).toContain('no cost price')
    expect(wrapper.find('[data-testid="enter-cost"]').exists()).toBe(false)
    wrapper.unmount()
  })
})
