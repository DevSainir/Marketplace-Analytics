import { mount } from '@vue/test-utils'
import { defineComponent, h, ref } from 'vue'

import { providePnlCurrencies, usePnlMoney } from '@/modules/finreports/pnlFormat'

/** Intl groups thousands with a no-break space; the assertions read plain ones. */
const plain = (text) => text.replace(/\s/g, ' ')

/** A P&L component: prints two figures. */
const Figures = defineComponent({
  setup() {
    const { money } = usePnlMoney()
    return () => h('p', `${money(57600)} | ${money(1539)}`)
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
  it('signs every figure, advertising included, in the payout currency', () => {
    // Rouble advertising is converted to soms where it is stored (02.10.2026),
    // so the advertising cells are in the payout currency like the rest.
    const wrapper = mount(pageWith({ settlement: 'KGS' }))

    expect(plain(wrapper.text())).toBe('KGS 57,600 | KGS 1,539')
  })

  it('prints bare figures when no page declared the currencies', () => {
    const wrapper = mount(Figures)

    expect(plain(wrapper.text())).toBe('57,600 | 1,539')
  })
})
