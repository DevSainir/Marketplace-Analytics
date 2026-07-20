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
  // An amount is meaningless until its question is answered — a budget with no
  // «Включали РК?» behind it is a number nobody can read.
  it('locks every amount while its question is unanswered', () => {
    const inputs = amountInputs(mountTable())

    expect(inputs).toHaveLength(3)
    expect(inputs.map((i) => i.attributes('disabled'))).toEqual(['', '', ''])
  })

  it('unlocks the budget once its own РК question is answered', () => {
    const [uniBudget, manualBudget, priceAmount] = amountInputs(
      mountTable({ [DAY]: { uni_rk_enabled: true } }),
    )

    expect(uniBudget.attributes('disabled')).toBeUndefined()
    // The other two questions are still unanswered, so they stay locked.
    expect(manualBudget.attributes('disabled')).toBe('')
    expect(priceAmount.attributes('disabled')).toBe('')
  })

  it('unlocks on a negative answer too — the choice is what matters', () => {
    const [uniBudget] = amountInputs(mountTable({ [DAY]: { uni_rk_enabled: false } }))

    expect(uniBudget.attributes('disabled')).toBeUndefined()
  })

  it('unlocks «На сколько» once «Меняли цену?» is picked', () => {
    const locked = amountInputs(mountTable({ [DAY]: { price_change: null } }))[2]
    const unlocked = amountInputs(mountTable({ [DAY]: { price_change: 'down' } }))[2]

    expect(locked.attributes('disabled')).toBe('')
    expect(unlocked.attributes('disabled')).toBeUndefined()
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
