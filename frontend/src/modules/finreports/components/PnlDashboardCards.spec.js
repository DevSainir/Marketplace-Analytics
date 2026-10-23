import { mount } from '@vue/test-utils'
import { h } from 'vue'

import PnlDashboardCards from '@/modules/finreports/components/PnlDashboardCards.vue'
import { providePriceBase } from '@/modules/finreports/priceBase'
import { formatNumber } from '@/core/utils/format'

const grouped = (n) => formatNumber(n)

/**
 * A dashboard shaped exactly like the backend's PnlDashboard.
 *
 * The figures are invented but add up: 588 net units at 4,150 each at the
 * seller's price, a 21.8% WB discount, so the buyer paid 1,908,236.40.
 */
function dashboard(overrides = {}) {
  return {
    sales: '2440200.00',
    paid: '1908236.40',
    sold_units: 640,
    returned_units: 52,
    return_rate_pct: '8.13',
    logistics: '318420.00',
    logistics_pct: '16.69',
    cogs: '358680.00',
    uncosted_count: 0,
    payout_net: '923415.90',
    other_deductions: '241318.70',
    advertising: '175900.00',
    excluded_count: 0,
    ...overrides,
  }
}

function mountCards(props = {}, { base } = {}) {
  // The page provides the price base; a card rendered alone falls back to the
  // seller's price, so only the other base needs a providing parent.
  const Page = {
    setup() {
      if (base) providePriceBase(base)
      return () => h(PnlDashboardCards, { dashboard: dashboard(), currency: 'KGS', ...props })
    },
  }
  return mount(Page, { global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } } })
}

describe('PnlDashboardCards', () => {
  it('renders all five cards including "Other deductions"', () => {
    const text = mountCards().text()

    expect(text).toContain('Sales')
    expect(text).toContain('Logistics')
    expect(text).toContain('Other deductions')
    expect(text).toContain('Cost price')
    expect(text).toContain('Total payout')
  })

  it('shows "Sales" at the seller price by default and says so', () => {
    const text = mountCards().text()

    expect(text).toContain(grouped(2440200))
    expect(text).toContain('At seller price')
    expect(text).not.toContain(grouped(1908236))
  })

  it('shows "Sales" at what the buyer paid when that base is chosen', () => {
    // WB's own report calls this figure the sale; at the seller's price the
    // card could not be matched against it.
    const text = mountCards({}, { base: 'paid' }).text()

    expect(text).toContain(grouped(1908236))
    expect(text).toContain('At customer price')
  })

  it('counts units net of returns, like the money above them', () => {
    // 640 sold, 52 back: "640 units" over a net figure made money and count disagree.
    expect(mountCards().text()).toContain(`${grouped(588)} units · 52 returned`)
  })

  it('takes the logistics share from the chosen base', () => {
    expect(mountCards().text()).toContain('13.05% of sales') // 318,420 / 2,440,200
    expect(mountCards({}, { base: 'paid' }).text()).toContain('16.69% of sales') // / 1,908,236
  })

  it('shows the advertising share under "Other deductions"', () => {
    const text = mountCards().text()

    expect(text).toContain(grouped(241319)) // WB's other-deductions total (rounded)
    expect(text).toContain('incl. advertising')
    expect(text).toContain(grouped(175900)) // the ad portion
  })

  it('notes how many SKUs are excluded on the "Total payout" card', () => {
    const text = mountCards({ dashboard: dashboard({ excluded_count: 3 }) }).text()

    expect(text).toContain('3 SKUs excluded')
    expect(mountCards({ dashboard: dashboard({ excluded_count: 1 }) }).text()).toContain(
      '1 SKU excluded',
    )
  })

  it('flags uncosted SKUs on the "Cost price" card', () => {
    const text = mountCards({ dashboard: dashboard({ uncosted_count: 4 }) }).text()

    expect(text).toContain('no cost price: 4 SKUs')
  })

  it('says in words that the "Cost price" card opens the cost editor', () => {
    // The header button is gone; a hover border alone did not read as a link,
    // and a phone has no hover.
    expect(mountCards({ dashboard: dashboard({ uncosted_count: 4 }) }).text()).toContain(
      'Fill in →',
    )
    expect(mountCards().text()).toContain('Edit →')
  })

  it('leads from the uncosted counter to those SKUs, and still to the editor', async () => {
    const wrapper = mountCards({ dashboard: dashboard({ uncosted_count: 4 }) })

    await wrapper.find('[data-testid="show-uncosted"]').trigger('click')

    expect(wrapper.findComponent(PnlDashboardCards).emitted('show-uncosted')).toHaveLength(1)
    expect(wrapper.text()).toContain('Fill in →')
  })

  it('offers no "Show them" when every SKU has a cost', () => {
    expect(mountCards().find('[data-testid="show-uncosted"]').exists()).toBe(false)
  })

  it('explains returns (not cancellations) via a tooltip', () => {
    expect(mountCards().html()).toContain('not a canceled order')
  })

  it('marks "Other deductions" as account-wide only when the view is filtered', () => {
    expect(mountCards().text()).not.toContain('whole invoice')
    expect(mountCards({ dashboard: dashboard({ filtered: true }) }).text()).toContain(
      'whole invoice',
    )
  })
})
