import { mount } from '@vue/test-utils'

import MetricsTable from '@/modules/monitoring/components/MetricsTable.vue'

const DAY = '2026-07-20'

/** The table needs a day and one metric row before it renders anything. */
function mountTable(dayActions = {}) {
  return mount(MetricsTable, {
    props: {
      days: [{ iso: DAY, label: '20.07.2026' }],
      rows: [{ key: 'spend', label: 'Затраты, ₽', tone: null, group: 'traffic', cells: [] }],
      dayActions,
    },
    global: { stubs: { Teleport: true } },
  })
}

/** The «Бюджет рекламы» / «На сколько» inputs of the «Действия» row, in order. */
function amountInputs(wrapper) {
  return wrapper.findAll('.day-action-amount input')
}

describe('«Действия» amount inputs', () => {
  // An amount only means something when the answer above it implies one, so an
  // unanswered question and a «Нет» both leave nothing to enter.
  it('locks every amount while its question is unanswered', () => {
    const inputs = amountInputs(mountTable())

    expect(inputs).toHaveLength(3)
    expect(inputs.map((i) => i.attributes('disabled'))).toEqual(['', '', ''])
  })

  it('unlocks the budget only for the campaign that was switched on', () => {
    const [uniBudget, manualBudget, priceAmount] = amountInputs(
      mountTable({ [DAY]: { uni_rk_enabled: true } }),
    )

    expect(uniBudget.attributes('disabled')).toBeUndefined()
    // The other two questions are still unanswered, so they stay locked.
    expect(manualBudget.attributes('disabled')).toBe('')
    expect(priceAmount.attributes('disabled')).toBe('')
  })

  it('keeps the budget locked on «Нет» — a campaign not run has no budget', () => {
    const [uniBudget] = amountInputs(mountTable({ [DAY]: { uni_rk_enabled: false } }))

    expect(uniBudget.attributes('disabled')).toBe('')
  })

  it('unlocks «На сколько» only for a real price direction', () => {
    const amountFor = (price_change) => amountInputs(mountTable({ [DAY]: { price_change } }))[2]

    expect(amountFor(null).attributes('disabled')).toBe('')
    expect(amountFor('none').attributes('disabled')).toBe('') // «Нет»
    expect(amountFor('up').attributes('disabled')).toBeUndefined()
    expect(amountFor('down').attributes('disabled')).toBeUndefined()
  })

  // The input is about to lock, so a number left behind it could neither be
  // read back nor cleared.
  it('clears a budget when the answer turns to «Нет»', async () => {
    const wrapper = mountTable({ [DAY]: { uni_rk_enabled: true, uni_rk_budget: 1500 } })

    await wrapper.findAll('.day-action-btn--no')[0].trigger('click')

    expect(wrapper.emitted('action')[0][0]).toEqual({
      day: DAY,
      patch: { uni_rk_enabled: false, uni_rk_budget: null },
    })
  })

  it('clears the price size when the direction turns to «Нет»', async () => {
    const wrapper = mountTable({ [DAY]: { price_change: 'up', price_change_amount: 200 } })
    const select = wrapper.find('.day-action-select')

    select.element.value = 'none'
    await select.trigger('change')

    expect(wrapper.emitted('action')[0][0]).toEqual({
      day: DAY,
      patch: { price_change: 'none', price_change_amount: null },
    })
  })

  it('keeps an amount locked while its day is saving', () => {
    const wrapper = mount(MetricsTable, {
      props: {
        days: [{ iso: DAY, label: '20.07.2026' }],
        rows: [{ key: 'spend', label: 'Затраты, ₽', tone: null, group: 'traffic', cells: [] }],
        dayActions: { [DAY]: { uni_rk_enabled: true } },
        actionSavingDays: new Set([DAY]),
      },
      global: { stubs: { Teleport: true } },
    })

    expect(amountInputs(wrapper)[0].attributes('disabled')).toBe('')
  })
})
