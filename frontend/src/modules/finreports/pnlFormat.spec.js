import { mount } from '@vue/test-utils'
import { defineComponent, h, ref } from 'vue'

import { providePnlCurrencies, usePnlMoney } from '@/modules/finreports/pnlFormat'

/** Intl groups thousands with a no-break space; the assertions read plain ones. */
const plain = (text) => text.replace(/\s/g, ' ')

/** A P&L component: prints one payout figure and one advertising figure. */
const Figures = defineComponent({
  setup() {
    const { money, adMoney } = usePnlMoney()
    return () => h('p', `${money(57600)} | ${adMoney(1539)}`)
  },
})

/** The page, declaring what its money is in. */
const pageWith = (currencies) =>
  defineComponent({
    setup() {
      providePnlCurrencies(ref(currencies))
      return () => h(Figures)
    },
  })

describe('usePnlMoney', () => {
  it('signs the payout in the settlement currency and advertising in the campaigns', () => {
    // Before 2026-08-20 WB billed ads in roubles while paying out in soms; a
    // single sign on both would misstate one of them.
    const wrapper = mount(pageWith({ settlement: 'KGS', ads: ['RUB'] }))

    expect(plain(wrapper.text())).toBe('57 600с | 1 539₽')
  })

  it('prints bare figures when no page declared the currencies', () => {
    const wrapper = mount(Figures)

    expect(plain(wrapper.text())).toBe('57 600 | 1 539')
  })
})
