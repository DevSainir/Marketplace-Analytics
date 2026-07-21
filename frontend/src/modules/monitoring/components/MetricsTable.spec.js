import { mount } from '@vue/test-utils'

import MetricsTable from '@/modules/monitoring/components/MetricsTable.vue'

const DAY = '2026-07-20'

/** The table needs a day and one metric row before it renders anything. */
function mountTable(dayActions = {}, extraProps = {}) {
  return mount(MetricsTable, {
    props: {
      days: [{ iso: DAY, label: '20.07.2026' }],
      rows: [{ key: 'spend', label: 'Затраты, ₽', tone: null, group: 'traffic', cells: [] }],
      dayActions,
      ...extraProps,
    },
    global: { stubs: { Teleport: true } },
  })
}

/** The «Бюджет рекламы» / «На сколько» inputs of the «Действия» row, in order. */
function amountInputs(wrapper) {
  return wrapper.findAll('.day-action-amount input')
}

/** The three «Действия» dropdowns: [Первая РК, Вторая РК, Меняли цену?]. */
function selects(wrapper) {
  return wrapper.findAll('.day-action-select')
}

describe('«Действия» amount inputs', () => {
  // An amount only means something once the choice above it is made — a budget
  // belongs to a chosen campaign, a size to a chosen price direction.
  it('locks every amount while its choice is unmade', () => {
    const inputs = amountInputs(mountTable())

    expect(inputs).toHaveLength(3)
    expect(inputs.map((i) => i.attributes('disabled'))).toEqual(['', '', ''])
  })

  it('unlocks a budget only once its own РК slot has a type', () => {
    const [firstBudget, secondBudget, priceAmount] = amountInputs(
      mountTable({ [DAY]: { first_rk_type: 'uni' } }),
    )

    expect(firstBudget.attributes('disabled')).toBeUndefined()
    // The other slot and the price are still unchosen, so they stay locked.
    expect(secondBudget.attributes('disabled')).toBe('')
    expect(priceAmount.attributes('disabled')).toBe('')
  })

  it('unlocks «На сколько» once a price direction is picked', () => {
    const amountFor = (price_change) => amountInputs(mountTable({ [DAY]: { price_change } }))[2]

    expect(amountFor(null).attributes('disabled')).toBe('')
    expect(amountFor('up').attributes('disabled')).toBeUndefined()
    expect(amountFor('down').attributes('disabled')).toBeUndefined()
  })

  it('keeps an amount locked while its day is saving', () => {
    const wrapper = mountTable(
      { [DAY]: { first_rk_type: 'uni' } },
      { actionSavingDays: new Set([DAY]) },
    )

    expect(amountInputs(wrapper)[0].attributes('disabled')).toBe('')
  })

  // The input is about to lock, so a number left behind it could neither be
  // read back nor cleared.
  it('clears a budget when its РК slot is cleared to «—»', async () => {
    const wrapper = mountTable({ [DAY]: { first_rk_type: 'uni', first_rk_budget: 1500 } })
    const first = selects(wrapper)[0]

    first.element.value = ''
    await first.trigger('change')

    expect(wrapper.emitted('action')[0][0]).toEqual({
      day: DAY,
      patch: { first_rk_type: null, first_rk_budget: null },
    })
  })

  it('clears the price size when the direction is cleared', async () => {
    const wrapper = mountTable({ [DAY]: { price_change: 'up', price_change_amount: 200 } })
    const price = selects(wrapper)[2]

    price.element.value = ''
    await price.trigger('change')

    expect(wrapper.emitted('action')[0][0]).toEqual({
      day: DAY,
      patch: { price_change: null, price_change_amount: null },
    })
  })
})

describe('«Первая РК» / «Вторая РК» synced dropdowns', () => {
  /** Option values of a select that are rendered `disabled`. */
  function disabledOptions(select) {
    return select
      .findAll('option')
      .filter((o) => o.attributes('disabled') !== undefined)
      .map((o) => o.attributes('value'))
  }

  it('disables in one slot the type already chosen in the other', () => {
    const [first, second] = selects(mountTable({ [DAY]: { first_rk_type: 'uni' } }))

    // «Единая» is taken by the first slot, so the second cannot pick it...
    expect(disabledOptions(second)).toContain('uni')
    // ...while the first slot, which owns it, keeps every option pickable.
    expect(disabledOptions(first)).toEqual([])
  })

  it('offers all four types when nothing is chosen', () => {
    const [first] = selects(mountTable())

    const values = first.findAll('option').map((o) => o.attributes('value'))
    expect(values).toEqual(['', 'uni', 'manual_search', 'manual_shelves', 'cpc'])
    expect(disabledOptions(first)).toEqual([])
  })

  it('emits the chosen type for its own slot', async () => {
    const wrapper = mountTable()
    const second = selects(wrapper)[1]

    second.element.value = 'manual_shelves'
    await second.trigger('change')

    expect(wrapper.emitted('action')[0][0]).toEqual({
      day: DAY,
      patch: { second_rk_type: 'manual_shelves' },
    })
  })
})

describe('«Меняли цену?» dropdown', () => {
  it('offers only Повысили and Понизили — no «Нет»', () => {
    const price = selects(mountTable())[2]

    const values = price.findAll('option').map((o) => o.attributes('value'))
    expect(values).toEqual(['', 'up', 'down'])
  })
})
