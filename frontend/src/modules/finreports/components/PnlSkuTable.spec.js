import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import PrimeVue from 'primevue/config'
import { beforeEach, vi } from 'vitest'

import PnlSkuTable from '@/modules/finreports/components/PnlSkuTable.vue'
import { formatNumber } from '@/core/utils/format'

// Groups ask the server for their list on mount; these tables need none.
vi.mock('@/modules/heatmap/api', () => ({ fetchGroups: vi.fn(async () => ({ items: [] })) }))

beforeEach(() => setActivePinia(createPinia()))

/** Tick one brand in the "Brands" menu, as a seller would. */
async function chooseBrand(wrapper, brand) {
  const trigger = wrapper.findAll('button.ui-trigger').find((b) => b.text().startsWith('Brands'))
  await trigger.trigger('click')
  const option = wrapper
    .findAll('[role="option"]')
    .find((o) => o.text().replace('✓', '').trim() === brand)
  await option.trigger('click')
}

/** Figures are grouped by the shared formatter — match through it, not by hand. */
const grouped = (n) => formatNumber(n)

/**
 * A row shaped exactly like the backend's PnlSkuRow.
 *
 * The figures are invented but consistent with each other: 640 sold, 52
 * returned, 588 net units at 4 150 each at the seller's price (2 440 200),
 * 21,8 % SPP. Profit is the payout minus the cost of goods and the ad spend.
 */
function row(overrides = {}) {
  return {
    nm_id: 953770957,
    sa_name: 'm-trx01-blk',
    subject_name: 'Trousers',
    brand_name: 'NORTH LINE',
    is_excluded: false,
    orders_units: 2140,
    sold_units: 640,
    returned_units: 52,
    return_rate_pct: '8.13',
    buyout_units: 640,
    decided_units: 2050,
    buyout_pct: '31.22',
    sales_amount: '2076992.00',
    returns_amount: '168755.60',
    revenue_paid: '1908236.40',
    revenue_seller_price: '2440200.00',
    spp_amount: '531963.60',
    spp_pct: '21.80',
    average_cheque: '3245.30',
    logistics_forward: '262400.00',
    logistics_return: '39180.00',
    logistics_total: '318420.00',
    logistics_pct: '13.05',
    penalties_total: '3095.50',
    penalties: [
      { reason: 'Discrepancies found in the product card', amount: '2480.00' },
      { reason: 'Paid storage of returns at the pickup point', amount: '615.50' },
    ],
    cost_price: '610.00',
    cogs: '358680.00',
    advertising: '214500.00',
    advertising_pct: '8.79',
    ad_bonus: '38600.00',
    advertising_cash: '175900.00',
    payout_for_goods: '1486250.10',
    payout_net: '1164734.60',
    net_profit: '630154.60',
    net_profit_pct: '25.82',
    roi_pct: '175.69',
    ...overrides,
  }
}

function mountTable(props = {}, { stubs, attachTo } = {}) {
  return mount(PnlSkuTable, {
    attachTo,
    props: { rows: [row()], unallocated: null, sizes: {}, currency: 'KGS', ...props },
    // The paginator reads $primevue.config at render time.
    global: { plugins: [PrimeVue], stubs },
  })
}

describe('per-SKU rows', () => {
  it('renders the requested columns for a fully-covered SKU', () => {
    const text = mountTable().text()

    expect(text).toContain('M-TRX01-BLK')
    expect(text).toContain('953770957') // "WB ID" (nm_id)
    expect(text).toContain('Trousers') // "Category" (subject)
    expect(text).toContain('NORTH LINE') // "Brand" (brand)
    expect(text).toContain(grouped(2140)) // orders — from the funnel, not the settlement
    expect(text).toContain('31.22%') // buyout — like the buyout rate in the WB seller portal
    expect(text).toContain('8.13%') // returns
    expect(text).toContain(grouped(2440200)) // sales — seller price (net of returns)
    expect(text).toContain(grouped(4150)) // average price — sales per net unit, same base
    expect(text).toContain('21.80%') // SPP
    expect(text).toContain(grouped(318420)) // logistics
    expect(text).toContain(grouped(358680)) // cost of goods
    expect(text).toContain(grouped(214500)) // advertising — gross, as WB's workspace shows it
    expect(text).toContain(`-${grouped(38600)}`) // bonuses — a deduction from it
    expect(text).toContain('175.69%') // ROI
    expect(text).not.toContain('ROMI')
    expect(text).toContain(grouped(1164735)) // payout
    expect(text).toContain(grouped(630155)) // net profit
  })

  it('shows "Sales" at the seller price, net of returns', () => {
    // The column carries revenue_seller_price (WB's retail price after the
    // agreed discount, before the WB discount) — the seller's own price, not
    // the amount the buyer paid after the WB discount.
    const text = mountTable().text()

    expect(text).toContain(grouped(2440200)) // seller price, net
  })

  it('keeps the row one line high: "2 reasons" beside the total, the reasons on a click', async () => {
    // The category is what tells a seller what a fine was for. Printed in the
    // cell it grew the row by a line per category.
    const wrapper = mountTable({}, { attachTo: document.body })
    const more = wrapper.find('[data-testid="penalty-reasons"]')

    expect(more.text()).toBe('2 reasons')
    expect(document.body.textContent).not.toContain('Penalty reasons')

    await more.trigger('click')

    expect(document.body.textContent).toContain('Discrepancies found in the product card')
    expect(document.body.textContent).toContain('Paid storage of returns at the pickup point')
    wrapper.unmount()
  })

  it('renders an em dash — never a zero — for an uncosted SKU profit', () => {
    // 0 KGS profit and "unknown" mean different things on a financial report:
    // a dash sends the seller to the cost editor, a zero tells them the SKU
    // breaks even.
    const wrapper = mountTable({
      rows: [row({ cost_price: null, cogs: null, net_profit: null, net_profit_pct: null })],
    })

    const profitCells = wrapper.findAll('td').filter((td) => td.text() === '—')
    expect(profitCells.length).toBeGreaterThan(0)
    expect(wrapper.text()).not.toContain('NaN')
  })

  it('renders dashes for orders and advertising when their history has no coverage', () => {
    const wrapper = mountTable({
      rows: [
        row({
          orders_units: null,
          advertising: null,
          advertising_pct: null,
          ad_bonus: null,
          advertising_cash: null,
        }),
      ],
    })

    expect(wrapper.text()).not.toContain('NaN')
    expect(wrapper.findAll('td').filter((td) => td.text() === '—').length).toBeGreaterThan(0)
  })

  it('shows the WB-funded share as a green deduction beside "Advertising"', () => {
    // The column reads as "minus this much", so the sign and the color are
    // both load-bearing: the API sends a positive magnitude precisely so the
    // arithmetic cannot subtract it twice, and the view is what makes it read
    // as money coming off the cost above it.
    const wrapper = mountTable()

    const bonus = wrapper.findAll('td').find((td) => td.text().includes(grouped(38600)))
    expect(bonus.text()).toContain(`-${grouped(38600)}`)
    expect(bonus.find('.text-status-positive').exists()).toBe(true)
  })

  it('renders an em dash, not a minus zero, for a SKU WB funded nothing of', () => {
    const wrapper = mountTable({ rows: [row({ ad_bonus: '0', advertising_cash: '214500.00' })] })

    expect(wrapper.text()).not.toContain('-0')
  })

  it('appends the account-level bucket as a visually distinct final row', () => {
    const wrapper = mountTable({
      unallocated: row({
        nm_id: 0,
        sa_name: 'Not tied to a SKU (whole invoice)',
        orders_units: null,
        advertising: null,
      }),
    })

    const rows = wrapper.findAll('tbody tr')
    expect(rows.at(-1).text()).toContain('Not tied to a SKU')
  })

  it('says "no sales" for an empty window instead of an empty grid', () => {
    expect(mountTable({ rows: [] }).text()).toContain('No sales in the period')
  })

  it('filters rows locally by the search query (article, nm, subject, brand)', async () => {
    const wrapper = mountTable({
      rows: [
        row({ nm_id: 1, sa_name: 'alpha', brand_name: 'NORTH LINE' }),
        row({ nm_id: 2, sa_name: 'beta', brand_name: 'OTHER' }),
      ],
    })

    await wrapper.find('input[type="search"]').setValue('beta')

    const bodies = wrapper.findAll('tbody tr')
    expect(bodies.length).toBe(1)
    expect(wrapper.text()).toContain('BETA')
    expect(wrapper.text()).not.toContain('ALPHA')
  })

  it('filters by brand via its menu', async () => {
    const wrapper = mountTable({
      rows: [
        row({ nm_id: 1, sa_name: 'alpha', brand_name: 'NORTH LINE' }),
        row({ nm_id: 2, sa_name: 'beta', brand_name: 'OTHER' }),
      ],
    })

    await chooseBrand(wrapper, 'OTHER')

    expect(wrapper.findAll('tbody tr').length).toBe(1)
    expect(wrapper.text()).toContain('BETA')
    expect(wrapper.text()).not.toContain('ALPHA')
  })

  it('emits toggle-exclusion when a row is marked "Exclude from total"', async () => {
    const wrapper = mountTable()

    await wrapper.find('input[type="checkbox"]').setValue(true)

    expect(wrapper.emitted('toggle-exclusion')).toBeTruthy()
    expect(wrapper.emitted('toggle-exclusion')[0][0]).toEqual({
      nmId: 953770957,
      excluded: true,
    })
  })

  it('emits a subtotal dashboard when filtered, and null when not', async () => {
    const wrapper = mountTable({
      rows: [
        row({ nm_id: 1, sa_name: 'alpha', brand_name: 'NORTH LINE', revenue_seller_price: '2500' }),
        row({ nm_id: 2, sa_name: 'beta', brand_name: 'OTHER', revenue_seller_price: '6500' }),
      ],
    })

    // Initial (no filter): the parent should fall back to the backend dashboard.
    const initial = wrapper.emitted('dashboard-change').at(-1)[0]
    expect(initial).toBeNull()

    await chooseBrand(wrapper, 'OTHER')

    const filtered = wrapper.emitted('dashboard-change').at(-1)[0]
    expect(filtered).not.toBeNull()
    expect(filtered.sales).toBe(6500) // seller price of only the OTHER-brand SKU
  })

  it('hides the account-level bucket while a filter is active', async () => {
    const wrapper = mountTable({
      rows: [row({ nm_id: 1, sa_name: 'alpha' })],
      unallocated: row({ nm_id: 0, sa_name: 'Not tied to a SKU (whole invoice)' }),
    })

    expect(wrapper.text()).toContain('Not tied to a SKU')

    await wrapper.find('input[type="search"]').setValue('alpha')

    expect(wrapper.text()).not.toContain('Not tied to a SKU')
  })

  // The heaviest test in the suite, and the only one with a timeout of its own.
  // Proving "the first page holds 50" means rendering fifty ~30-column rows in
  // jsdom, which is irreducible — so the fixture was cut to the minimum that
  // states the claim (about 1.4s -> ~0.6s) and the bound was then raised to cover
  // what is left. Measured with the whole backend suite running alongside it,
  // this test takes 3.0-4.5s; against the 5s default that is a coin flip, which
  // is exactly how it failed. The number below is head-room for a contended
  // machine, NOT a performance budget for the component — if this test ever
  // approaches it on an idle box, something in the table got slow.
  it('offers 50/100/150/200 rows per page and defaults to 50', async () => {
    // A native select, not the paginator's built-in dropdown — PrimeVue runs
    // unstyled here and its Select renders collapsed without a theme.
    //
    // Fifty-one rows, not a hundred and twenty: the claim is "the first page
    // holds 50, a bigger page holds the rest", and 51 is the smallest fixture
    // that can state it.
    const many = Array.from({ length: 51 }, (_, i) => row({ nm_id: 500 + i, penalties: [] }))
    // The card projection is stubbed for this test alone — it is the OTHER
    // half of the same rows, nothing here asserts on it, and being unpaginated
    // by design it renders all 51 while the table renders 50. Dropping it takes
    // the run from ~0.6-1s to a steady ~0.6s: the VARIANCE is the point, since
    // what broke was a 5s timeout on a loaded machine, not a mean.
    const wrapper = mountTable({ rows: many }, { stubs: { PnlSkuCards: true } })

    const select = wrapper.find('select#sku-page-size')
    expect(select.exists()).toBe(true)
    expect([...select.element.options].map((o) => o.value)).toEqual(['50', '100', '150', '200'])
    expect(wrapper.findAll('tbody tr').length).toBe(50)

    await select.setValue('100')

    expect(wrapper.findAll('tbody tr').length).toBe(51) // 100/page → all fit
  }, 20_000)
})

describe('bounds, sizes and "Total"', () => {
  it('paints a share past the upper bound red', () => {
    // 43 % logistics is above the workspace's p90, and that is the very row
    // the report gets opened for.
    const wrapper = mountTable({
      rows: [row({ revenue_seller_price: '800000.00', logistics_total: '344000.00' })],
    })

    const cell = wrapper.findAll('td').find((td) => td.text().includes('43.00%'))
    expect(cell.find('.text-status-negative').exists()).toBe(true)
  })

  it('paints what beats the lower bound green', () => {
    const wrapper = mountTable({ rows: [row({ roi_pct: '212.40' })] })

    const cell = wrapper.findAll('td').find((td) => td.text() === '212.40%')
    expect(cell.find('.text-status-positive').exists()).toBe(true)
  })

  it('leaves what lies within the usual spread unpainted', () => {
    // Half a table colored in is not highlighting anything.
    const wrapper = mountTable({
      rows: [
        row({
          revenue_seller_price: '800000.00',
          logistics_total: '192000.00',
          roi_pct: '120.00',
        }),
      ],
    })

    const logistics = wrapper.findAll('td').find((td) => td.text().includes('24.00%'))
    const roi = wrapper.findAll('td').find((td) => td.text() === '120.00%')
    expect(logistics.find('.text-status-negative').exists()).toBe(false)
    expect(roi.find('.text-status-negative').exists()).toBe(false)
    expect(roi.find('.text-status-positive').exists()).toBe(false)
  })

  it('shows a "Total" row with the sum of each column', () => {
    const wrapper = mountTable({
      rows: [
        row({ nm_id: 1, revenue_seller_price: '1200', logistics_total: '150' }),
        row({ nm_id: 2, revenue_seller_price: '2600', logistics_total: '350' }),
      ],
    })

    const footer = wrapper.find('tfoot')
    expect(footer.exists()).toBe(true)
    expect(footer.text()).toContain('Total')
    // A prose label, never a SKU code: `formatSku` would have shouted it.
    expect(footer.text()).not.toContain('TOTAL')
    expect(footer.text()).toContain(grouped(3800)) // sales
    expect(footer.text()).toContain(grouped(500)) // logistics
  })

  it('leaves the rows marked "Exclude from total" out of "Total"', () => {
    const wrapper = mountTable({
      rows: [
        row({ nm_id: 1, revenue_seller_price: '1500' }),
        row({ nm_id: 2, revenue_seller_price: '7000', is_excluded: true }),
      ],
    })

    const footer = wrapper.find('tfoot')
    expect(footer.text()).toContain(grouped(1500))
    expect(footer.text()).not.toContain(grouped(8500))
    expect(footer.text()).toContain('Total (1 excluded)')
  })

  it('asks the parent for sizes on a click and draws them under the row', async () => {
    const wrapper = mountTable()

    await wrapper.find('button.pnl-expander').trigger('click')

    expect(wrapper.emitted('load-sizes')).toBeTruthy()
    expect(wrapper.emitted('load-sizes')[0][0]).toBe(953770957)
    // While there is no answer yet it shows that counting is under way, not an empty row.
    expect(wrapper.text()).toContain('Loading…')
  })

  it('draws sizes as rows under the article, with no "Total" of their own', async () => {
    const wrapper = mountTable({
      sizes: {
        953770957: {
          loading: false,
          error: '',
          data: {
            nm_id: 953770957,
            sa_name: 'm-trx01-blk',
            currency: 'KGS',
            rows: [
              {
                ts_name: '42/170-177',
                sold_units: 96,
                returned_units: 8,
                delivered_units: 410,
                buyout_pct: '23.41',
                revenue_paid: '285586.40',
                revenue_seller_price: '365200.00',
                average_price: '4150.00',
                logistics_total: '68540.00',
                logistics_pct: '24.00',
                logistics_per_delivery: '167.17',
                penalties_total: '0',
                payout_net: '139620.80',
              },
            ],
          },
        },
      },
    })

    await wrapper.find('button.pnl-expander').trigger('click')

    expect(wrapper.text()).toContain('42/170-177')
    // The sizes add up to the article row above them; a second "Total" repeated it.
    expect(wrapper.text()).not.toContain('Size total')
    const rows = wrapper.findAll('tbody tr')
    expect(rows[1].classes()).toContain('pnl-tree-child')
    expect(rows[1].text()).toContain('42/170-177')
    // The backend sends Decimals as strings; the percentage formatter accepts
    // only a number, so without the conversion the whole column silently turns
    // into "—".
    expect(wrapper.text()).toContain('23.41%')
    // The logistics share is taken from the size's revenue at the chosen base:
    // 68,540 / 365,200, not the backend's share at the buyer's price.
    expect(wrapper.text()).toContain('18.77%')
  })
})

describe('ACoS: zero means "no ads ran", not "ads ran cheaply"', () => {
  it('does not paint a zero ACoS green', () => {
    const wrapper = mountTable({ rows: [row({ advertising: '0', advertising_pct: '0' })] })

    const zeros = wrapper.findAll('td').filter((td) => td.text() === '0.00%')
    expect(zeros.length).toBeGreaterThan(0)
    expect(zeros.some((td) => td.find('.text-status-positive').exists())).toBe(false)
  })

  it('stands as a column of its own, leaving only the amount under "Advertising"', () => {
    const wrapper = mountTable()

    const headers = wrapper.findAll('th').map((th) => th.text())
    expect(headers.some((text) => text.startsWith('ACoS'))).toBe(true)
    // 214,500 / 2,440,200 — at the seller's price.
    expect(wrapper.findAll('td').some((td) => td.text() === '8.79%')).toBe(true)
    expect(wrapper.text()).not.toContain('(8.79%)')
  })
})
