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
import { METRICS, cellFor } from '@/modules/abTests/variantColumns'

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
  it('shows no ⓘ hints and no «Побед» row', () => {
    const wrapper = build([variant(MAIN)])

    expect(wrapper.find('[data-testid="hint"]').exists()).toBe(false)
    expect(wrapper.findAll('tbody th').map((th) => th.text())).toEqual([
      'Показов',
      'Кликов',
      'CTR',
      'Результат',
      'Отклонение CTR от лучшего',
      'Кругов',
    ])
  })

  it('names the leader on the points line and zeroes it on the relative one', () => {
    // Two lines, two jobs: «Результат» carries the number and «Отклонение»
    // carries the verdict. Putting «Лучший» on both would leave one of them
    // with nothing of its own to say.
    const wrapper = build([
      variant(MAIN, { is_original: true, click_through: 3.34, ctr_result: 0, ctr_gap: 0 }),
      variant(ONE, { click_through: 2.09, ctr_result: -37, ctr_gap: 1.25 }),
    ])

    expect(row(wrapper, 'Результат')).toEqual(['0%', '-37%'])
    expect(row(wrapper, 'Отклонение')).toEqual(['Лучший', '1.25% ↓'])
  })

  it('crowns the highest CTR as the wire sends it, two digits against one', () => {
    // Figures in the shape the API really sends: `Decimal` serialises to a
    // string, and "8.92" > "11.24" as text. Every fixture above uses numbers,
    // which is how that went unseen.
    const wrapper = build([
      variant(MAIN, { click_through: '11.24', ctr_result: '0.00', ctr_gap: '0.00' }),
      variant(ONE, { click_through: '6.91', ctr_result: '-38.52', ctr_gap: '4.33' }),
      variant(TWO, { click_through: '8.92', ctr_result: '-20.64', ctr_gap: '2.32' }),
    ])

    expect(row(wrapper, 'Отклонение')).toEqual(['Лучший', '4.33% ↓', '2.32% ↓'])
  })

  it('calls the captured photo «Главное» instead of «Вариант 0»', () => {
    const wrapper = build([variant(MAIN, { is_original: true, position: 0 })])

    expect(wrapper.text()).toContain('Главное')
    expect(wrapper.text()).not.toContain('Вариант 0')
  })

  it.each([
    ['-5', -5, 'ab-grid__value--positive'],
    ['-20', -20, 'ab-grid__value--warning'],
    ['-51', -51, 'ab-grid__value--negative'],
  ])('shows a %s%% gap in the %s band', (_label, result, expected) => {
    const wrapper = build([
      variant(MAIN, { click_through: 10, ctr_result: 0 }),
      variant(ONE, { click_through: 5, ctr_result: result }),
    ])

    const cells = wrapper.findAll('tbody tr')[3].findAll('td')
    expect(cells[1].classes()).toContain(expected)
  })
})

describe('an excluded photo', () => {
  it('keeps its numbers, greyed rather than gone', () => {
    const wrapper = build([
      variant(MAIN, { click_through: 3 }),
      variant(ONE, { is_excluded: true, views: 8_000, click_through: 1 }),
    ])

    expect(wrapper.findAll('[data-testid="variant-column"]')).toHaveLength(2)
    expect(row(wrapper, 'Показов')).toEqual(['10,000', '8,000'].map((s) => s.replace(' ', ' ')))
    expect(wrapper.findAll('[data-testid="variant-column"]')[1].classes()).toContain('is-excluded')
  })

  it('cannot be the leader of a comparison it left', () => {
    const wrapper = build([
      variant(MAIN, { click_through: 3 }),
      variant(ONE, { is_excluded: true, click_through: 9 }),
    ])

    expect(row(wrapper, 'Отклонение')[0]).toBe('Лучший')
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

    expect(row(wrapper, 'Показов')).toEqual(['1,000', '1,000'].map((s) => s.replace(' ', ' ')))
    expect(row(wrapper, 'CTR')).toEqual(['5.00%', '1.00%'])
    expect(row(wrapper, 'Результат')).toEqual(['0%', '-80%'])
  })

  it('leaves the whole-test columns alone', () => {
    const wrapper = mount(VariantResultsTable, {
      props: {
        round: 2,
        test: {
          id: 'test-1',
          rounds_completed: 2,
          variants: [variant(MAIN, { rounds_played: 5 })],
          history: [{ variant_id: MAIN, round_number: 2, views: 100, clicks: 5 }],
        },
      },
    })

    // «Кругов» is a property of the test, not of a lap: "laps in this lap" is
    // always one.
    expect(row(wrapper, 'Кругов')).toEqual(['5'])
  })
})

describe('how a figure is coloured', () => {
  it('hands back a tone, never a utility class', () => {
    // The regression this exists for was invisible: every cell carried a
    // `text-status-*` class, every class-presence assertion passed, and the
    // whole grid rendered in plain black — because the scoped
    // `.ab-grid__value` sets `color` and outranks a utility on the same
    // element. The colour has to come from the sheet's own modifier, so what
    // this function returns must be a tone name and nothing else.
    const variant = {
      variant_id: MAIN,
      click_through: 1,
      ctr_result: -50,
      ctr_gap: 1,
    }
    const tones = METRICS.map((metric) => cellFor(variant, metric, { leaderId: null }).tone)

    expect(tones.some((tone) => tone.includes('text-'))).toBe(false)
    expect(new Set(tones)).toEqual(new Set(['', 'negative']))
  })
})
