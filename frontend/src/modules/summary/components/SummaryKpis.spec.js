/**
 * What the buyout card says about its own period.
 *
 * The figure can come from two places — the chosen period, or the standing
 * "earlier days" window when that period is too fresh to have been answered —
 * and the two are indistinguishable as a bare percentage. The note is the only
 * thing that tells them apart, so it is worth a test: it shipped once as the
 * old wording because a text edit silently failed to apply and nothing checked.
 */
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import SummaryKpis from '@/modules/summary/components/SummaryKpis.vue'

const KPI = {
  revenue_paid: '1000',
  revenue_seller: '1200',
  margin: '300',
  sold_units: 10,
  orders: 100,
  buyouts: 27,
  buyout_decided: 100,
  buyout_lagged: false,
  uncosted_skus: 0,
  penalties: '0',
  ad_spend: '100',
}

const card = (wrapper, label) =>
  wrapper.findAll('.sum-kpi').find((node) => node.text().startsWith(label))

describe('the buyout card', () => {
  it('reports the period when the period answered for itself', () => {
    const wrapper = mount(SummaryKpis, { props: { kpi: KPI, currency: 'KGS' } })

    const buyout = card(wrapper, 'Buyout rate')
    expect(buyout.text()).toContain('27')
    expect(buyout.text()).toContain('of delivered')
    expect(buyout.find('[data-testid="hint"]').exists()).toBe(false)
  })

  it('says so, and explains, when the figure is the standing average', () => {
    const kpi = { ...KPI, buyout_lagged: true }

    const wrapper = mount(SummaryKpis, { props: { kpi, currency: 'KGS' } })

    const buyout = card(wrapper, 'Buyout rate')
    expect(buyout.text()).toContain('Average over earlier days')
    expect(buyout.find('[data-testid="hint"]').attributes('aria-label')).toContain(
      "haven't had time to be bought out",
    )
  })
})
