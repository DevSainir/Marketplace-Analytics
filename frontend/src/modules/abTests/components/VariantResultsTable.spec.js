/**
 * The result grid.
 *
 * What is pinned here is the reading of a number, not its arithmetic — the
 * backend computes the figures and has its own tests. This component decides
 * what a figure *means* on screen: which column is the leader, which colour a
 * gap is shown in, and what an excluded photo looks like. Each of those is a
 * claim, and each can be wrong while every number in the table is right.
 *
 * The exclusion cases matter most. «Убрано» has to keep the numbers that were
 * the reason for excluding it, and it must not quietly become the leader of a
 * comparison it is no longer part of.
 */
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import VariantResultsTable from '@/modules/abTests/components/VariantResultsTable.vue'

const MAIN = '00000000-0000-7000-8000-00000000000a'
const ONE = '00000000-0000-7000-8000-00000000000b'
const TWO = '00000000-0000-7000-8000-00000000000c'

function variant(id, overrides = {}) {
  return {
    variant_id: id,
    position: 1,
    is_original: false,
    is_active: false,
    is_excluded: false,
    views: 10_000,
    clicks: 300,
    click_through: 3,
    ctr_gap: 0,
    ctr_result: 0,
    rounds_played: 5,
    rounds_won: 0,
    ...overrides,
  }
}

function build(variants, extra = {}) {
  return mount(VariantResultsTable, {
    props: {
      test: {
        id: 'test-1',
        status: 'running',
        rounds_completed: 5,
        history: [],
        variants,
        ...extra,
      },
    },
  })
}

/**
 * The exclusion control in the TABLE.
 *
 * The component renders two things: the table and, below `sm`, the pager. Both
 * carry a `toggle-exclusion` control, so an unscoped query finds whichever the
 * DOM happens to put first. These cases are about the table's.
 */
function tableCross(wrapper) {
  return wrapper.get('[data-testid="variant-column"] [data-testid="toggle-exclusion"]')
}

/** The cells of one metric row, by its label. */
function row(wrapper, label) {
  const tr = wrapper.findAll('tbody tr').find((r) => r.find('th').text().startsWith(label))
  return tr.findAll('td').map((td) => td.text())
}

describe('what the table says about a photo', () => {
  it('names the leader rather than printing it a zero', () => {
    const wrapper = build([
      variant(MAIN, { is_original: true, click_through: 3.34, ctr_result: 0, ctr_gap: 0 }),
      variant(ONE, { click_through: 2.09, ctr_result: -37, ctr_gap: 1.25 }),
    ])

    expect(row(wrapper, 'Результат')).toEqual(['Лучший', '-37%'])
    expect(row(wrapper, 'Отклонение')).toEqual(['0%', '1,25% ↓'])
  })

  it('calls the captured photo «Главное» instead of «Вариант 0»', () => {
    const wrapper = build([variant(MAIN, { is_original: true, position: 0 })])

    expect(wrapper.text()).toContain('Главное')
    expect(wrapper.text()).not.toContain('Вариант 0')
  })

  it.each([
    ['-5', -5, 'text-status-positive'],
    ['-20', -20, 'text-status-warning'],
    ['-51', -51, 'text-status-negative'],
  ])('shows a %s%% gap as %s', (_label, result, expected) => {
    const wrapper = build([
      variant(MAIN, { click_through: 10, ctr_result: 0 }),
      variant(ONE, { click_through: 5, ctr_result: result }),
    ])

    const cells = wrapper.findAll('tbody tr')[3].findAll('td')
    expect(cells[1].classes()).toContain(expected)
  })

  it('declines a Russian count correctly', () => {
    const wrapper = build([
      variant(MAIN, { rounds_won: 1 }),
      variant(ONE, { rounds_won: 4 }),
      variant(TWO, { rounds_won: 0 }),
    ])

    expect(row(wrapper, 'Побед')).toEqual(['1 раз', '4 раза', '0 раз'])
  })
})

describe('an excluded photo', () => {
  it('keeps its numbers, greyed rather than gone', () => {
    const wrapper = build([
      variant(MAIN, { click_through: 3 }),
      variant(ONE, { is_excluded: true, views: 8_000, click_through: 1 }),
    ])

    expect(wrapper.findAll('[data-testid="variant-column"]')).toHaveLength(2)
    expect(row(wrapper, 'Показов')).toEqual(['10 000', '8 000'].map((s) => s.replace(' ', ' ')))
    expect(wrapper.findAll('[data-testid="variant-column"]')[1].classes()).toContain('is-excluded')
  })

  it('cannot be the leader of a comparison it left', () => {
    const wrapper = build([
      variant(MAIN, { click_through: 3 }),
      variant(ONE, { is_excluded: true, click_through: 9 }),
    ])

    expect(row(wrapper, 'Результат')[0]).toBe('Лучший')
  })

  it('offers to come back, without needing a hover to find the control', () => {
    const wrapper = build([variant(MAIN, { is_excluded: true })])
    const button = tableCross(wrapper)

    // `v-show` hides by setting `display: none`; no style attribute at all
    // means the control is drawn without the mouse having to find it first.
    expect(button.attributes('title')).toBe('Вернуть в ротацию')
    expect(button.attributes('style') ?? '').not.toContain('display: none')
  })

  it('emits the intent rather than deciding for itself', async () => {
    const wrapper = build([variant(MAIN)])

    await tableCross(wrapper).trigger('click')

    expect(wrapper.emitted('exclude')).toEqual([[MAIN, true]])
  })
})

describe('filtering to one lap', () => {
  it('recomputes the figures from that lap alone', () => {
    const wrapper = mount(VariantResultsTable, {
      props: {
        round: 2,
        test: {
          id: 'test-1',
          rounds_completed: 2,
          variants: [variant(MAIN), variant(ONE)],
          history: [
            { variant_id: MAIN, round_number: 1, views: 9_000, clicks: 270 },
            { variant_id: MAIN, round_number: 2, views: 1_000, clicks: 50 },
            { variant_id: ONE, round_number: 2, views: 1_000, clicks: 10 },
          ],
        },
      },
    })

    expect(row(wrapper, 'Показов')).toEqual(['1 000', '1 000'].map((s) => s.replace(' ', ' ')))
    expect(row(wrapper, 'CTR')).toEqual(['5,00%', '1,00%'])
    expect(row(wrapper, 'Результат')).toEqual(['Лучший', '-80%'])
  })

  it('leaves the whole-test columns alone', () => {
    const wrapper = mount(VariantResultsTable, {
      props: {
        round: 2,
        test: {
          id: 'test-1',
          rounds_completed: 2,
          variants: [variant(MAIN, { rounds_played: 5, rounds_won: 3 })],
          history: [{ variant_id: MAIN, round_number: 2, views: 100, clicks: 5 }],
        },
      },
    })

    // «Побед» and «Кругов» are properties of the test, not of a lap: «побед в
    // этом круге» is one or nothing, which is not a column worth having.
    expect(row(wrapper, 'Побед')).toEqual(['3 раза'])
    expect(row(wrapper, 'Кругов')).toEqual(['5'])
  })
})
