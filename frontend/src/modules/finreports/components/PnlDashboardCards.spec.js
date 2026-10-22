import { mount } from '@vue/test-utils'
import { h } from 'vue'

import PnlDashboardCards from '@/modules/finreports/components/PnlDashboardCards.vue'
import { providePriceBase } from '@/modules/finreports/priceBase'
import { formatNumber } from '@/core/utils/format'

const grouped = (n) => formatNumber(n)

/**
 * A dashboard shaped exactly like the backend's PnlDashboard.
 *
 * The figures are invented but add up: 588 net units at 4 150 each at the
 * seller's price, 21,8 % SPP, so the buyer paid 1 908 236,40.
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
  it('renders all five cards including «Прочие удержания»', () => {
    const text = mountCards().text()

    expect(text).toContain('Продажи')
    expect(text).toContain('Логистика')
    expect(text).toContain('Прочие удержания')
    expect(text).toContain('Себестоимость')
    expect(text).toContain('Итого к оплате')
  })

  it('shows «Продажи» at the seller price by default and says so', () => {
    const text = mountCards().text()

    expect(text).toContain(grouped(2440200))
    expect(text).toContain('По цене селлера')
    expect(text).not.toContain(grouped(1908236))
  })

  it('shows «Продажи» at what the buyer paid when that base is chosen', () => {
    // WB's own report calls this figure «Продажа»; at the seller's price the
    // card could not be matched against it.
    const text = mountCards({}, { base: 'paid' }).text()

    expect(text).toContain(grouped(1908236))
    expect(text).toContain('По цене реализации')
  })

  it('counts units net of returns, like the money above them', () => {
    // 640 sold, 52 back: «640 шт» over a net figure made money and count disagree.
    expect(mountCards().text()).toContain(`${grouped(588)} шт · возвраты 52 шт`)
  })

  it('takes the logistics share from the chosen base', () => {
    expect(mountCards().text()).toContain('13.05% от продаж') // 318 420 / 2 440 200
    expect(mountCards({}, { base: 'paid' }).text()).toContain('16.69% от продаж') // / 1 908 236
  })

  it('shows the advertising share under «Прочие удержания»', () => {
    const text = mountCards().text()

    expect(text).toContain(grouped(241319)) // WB's «Прочие удержания» total (rounded)
    expect(text).toContain('в т.ч. реклама')
    expect(text).toContain(grouped(175900)) // the ad portion
  })

  it('notes how many SKUs are excluded on the «Итого к оплате» card', () => {
    const text = mountCards({ dashboard: dashboard({ excluded_count: 3 }) }).text()

    expect(text).toContain('исключено 3 SKU')
  })

  it('flags uncosted SKUs on the «Себестоимость» card', () => {
    const text = mountCards({ dashboard: dashboard({ uncosted_count: 4 }) }).text()

    expect(text).toContain('без себестоимости: 4 SKU')
  })

  it('says in words that the «Себестоимость» card opens the cost editor', () => {
    // The header button is gone; a hover border alone did not read as a link,
    // and a phone has no hover.
    expect(mountCards({ dashboard: dashboard({ uncosted_count: 4 }) }).text()).toContain(
      'Заполнить →',
    )
    expect(mountCards().text()).toContain('Изменить →')
  })

  it('leads from the uncosted counter to those SKUs, and still to the editor', async () => {
    const wrapper = mountCards({ dashboard: dashboard({ uncosted_count: 4 }) })

    await wrapper.find('[data-testid="show-uncosted"]').trigger('click')

    expect(wrapper.findComponent(PnlDashboardCards).emitted('show-uncosted')).toHaveLength(1)
    expect(wrapper.text()).toContain('Заполнить →')
  })

  it('offers no «Показать их» when every SKU has a cost', () => {
    expect(mountCards().find('[data-testid="show-uncosted"]').exists()).toBe(false)
  })

  it('explains «возвраты» (returns, not cancellations) via a tooltip', () => {
    expect(mountCards().html()).toContain('а не отменённый заказ')
  })

  it('marks «Прочие удержания» as account-wide only when the view is filtered', () => {
    expect(mountCards().text()).not.toContain('на весь счёт')
    expect(mountCards({ dashboard: dashboard({ filtered: true }) }).text()).toContain(
      'на весь счёт',
    )
  })
})
