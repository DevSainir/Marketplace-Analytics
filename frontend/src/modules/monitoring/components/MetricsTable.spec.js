import { mount } from '@vue/test-utils'

import MetricsTable from '@/modules/monitoring/components/MetricsTable.vue'
import { DAY_COLSPAN } from '@/modules/monitoring/metricsMatrix'

const DAY = '2026-07-20'

/** The table needs a day and one metric row before it renders anything. */
function mountTable(dayActions = {}, extraProps = {}) {
  return mount(MetricsTable, {
    props: {
      days: [{ iso: DAY, label: '20 Jul 2026' }],
      rows: [{ key: 'spend', label: 'Spend', tone: null, group: 'traffic', cells: [] }],
      dayActions,
      ...extraProps,
    },
    global: { stubs: { Teleport: true } },
  })
}

/** The "Ad budget" / "By how much" inputs of the "Actions" row, in order. */
function amountInputs(wrapper) {
  return wrapper.findAll('.day-action-amount input')
}

/** The three "Actions" dropdowns: ["Campaign 1", "Campaign 2", "Price changed?"]. */
function selects(wrapper) {
  return wrapper.findAll('.day-action-select')
}

describe('"Actions" amount inputs', () => {
  // An amount only means something once the choice above it is made — a budget
  // belongs to a chosen campaign, a size to a chosen price direction.
  it('locks every amount while its choice is unmade', () => {
    const inputs = amountInputs(mountTable())

    expect(inputs).toHaveLength(3)
    expect(inputs.map((i) => i.attributes('disabled'))).toEqual(['', '', ''])
  })

  it('unlocks a budget only once its own campaign slot has a type', () => {
    const [firstBudget, secondBudget, priceAmount] = amountInputs(
      mountTable({ [DAY]: { first_rk_type: 'uni' } }),
    )

    expect(firstBudget.attributes('disabled')).toBeUndefined()
    // The other slot and the price are still unchosen, so they stay locked.
    expect(secondBudget.attributes('disabled')).toBe('')
    expect(priceAmount.attributes('disabled')).toBe('')
  })

  it('unlocks "By how much" once a price direction is picked', () => {
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
  it('clears a budget when its campaign slot is cleared to "—"', async () => {
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

describe('"Campaign 1" / "Campaign 2" synced dropdowns', () => {
  /** Option values of a select that are rendered `disabled`. */
  function disabledOptions(select) {
    return select
      .findAll('option')
      .filter((o) => o.attributes('disabled') !== undefined)
      .map((o) => o.attributes('value'))
  }

  it('disables in one slot the type already chosen in the other', () => {
    const [first, second] = selects(mountTable({ [DAY]: { first_rk_type: 'uni' } }))

    // "Unified bid" is taken by the first slot, so the second cannot pick it...
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

describe('"Price changed?" dropdown', () => {
  it('offers only Raised and Lowered — no "No"', () => {
    const price = selects(mountTable())[2]

    const values = price.findAll('option').map((o) => o.attributes('value'))
    expect(values).toEqual(['', 'up', 'down'])
  })
})

describe('table composition', () => {
  // The rows below the metrics are separate components, but they must render
  // as <tbody> sections of the SAME <table>. That is what keeps every row's day
  // columns aligned with the metrics above them and lets one scroll container
  // move all of them together — a child that rendered its own <table> (or a
  // wrapper element) would look right until the ribbon was scrolled sideways.
  it('renders every row section inside the one table', () => {
    const wrapper = mountTable({}, { priceRows: [{ key: 'seller_price', cells: [] }] })

    const tables = wrapper.findAll('table')
    const sections = wrapper.findAll('table > tbody')

    expect(tables).toHaveLength(1)
    expect(sections.map((s) => s.classes().find((c) => c.startsWith('matrix-')))).toEqual([
      'matrix-metrics',
      'matrix-blocks',
      'matrix-comments',
      'matrix-actions',
    ])
  })

  it('lets "Overall" and "Organic" break onto a second line instead of clipping', () => {
    // Both are wider than their one-column cell at 1280px, and Chromium does
    // not hyphenate a capitalised word by itself.
    const wrapper = mountTable()

    const groups = wrapper.findAll('thead tr:nth-child(2) th').map((th) => th.text())

    expect(groups).toContain('Over\u00adall')
    expect(groups).toContain('Or\u00adganic')
  })

  it('heads the CPC group with its own Search/Shelves zone pair', () => {
    // The CPC campaigns are billed per click, so they read as their own
    // traffic type rather than as more zones of a CPM column.
    const wrapper = mountTable()

    // A soft hyphen is invisible until it breaks a line, so it is read past here.
    const groups = wrapper
      .findAll('thead tr:nth-child(2) th')
      .map((th) => th.text().replaceAll('\u00ad', ''))
    const zones = wrapper.findAll('thead tr:nth-child(3) th').map((th) => th.text())

    expect(groups).toEqual([
      'Traffic type',
      'Unified bid',
      'Manual search',
      'Manual shelves',
      'CPC',
      'Overall',
      'Organic',
    ])
    expect(zones.slice(-2)).toEqual(['Search', 'Shelves'])
  })

  it('keeps every day column the same width across all sections', () => {
    const days = [
      { iso: '2026-07-19', label: '19 Jul 2026' },
      { iso: DAY, label: '20 Jul 2026' },
    ]
    const wrapper = mount(MetricsTable, {
      props: {
        days,
        rows: [{ key: 'spend', label: 'Spend', tone: null, group: 'traffic', cells: [] }],
        priceRows: [{ key: 'seller_price', cells: [] }],
      },
      global: { stubs: { Teleport: true } },
    })

    // Each section spans the label column plus every grid column of its days;
    // a mismatch here is exactly how a section drifts out of alignment.
    const spans = wrapper.findAll('tr.matrix-gap td').map((td) => td.attributes('colspan'))

    expect(spans.length).toBeGreaterThan(0)
    expect(new Set(spans)).toEqual(new Set([String(1 + days.length * DAY_COLSPAN)]))
  })

  it('sizes every leaf of every day through the colgroup', () => {
    // The table is laid out fixed, so the columns decide the widths: one for
    // the labels, then one per leaf, "Manual shelves" on its own class.
    const wrapper = mount(MetricsTable, {
      props: {
        days: [
          { iso: DAY, label: '20 Jul 2026' },
          { iso: '2026-07-21', label: '21 Jul 2026' },
        ],
        rows: [{ key: 'spend', label: 'Spend', tone: null, group: 'traffic', cells: [] }],
      },
      global: { stubs: { Teleport: true } },
    })

    const cols = wrapper.findAll('colgroup col')

    expect(cols).toHaveLength(1 + 2 * DAY_COLSPAN)
    expect(cols.filter((col) => col.classes('matrix-col--shelves'))).toHaveLength(2)
  })

  it('forwards a day-note edit from the comments section to its own listener', async () => {
    const wrapper = mountTable()

    // The notes row opens EXPANDED, so the inputs are there to be typed into
    // without a click first — which is itself part of what this asserts still
    // works through the component boundary.
    const input = wrapper.find('.comment-header-input')
    await input.setValue('New title')
    await input.trigger('blur')

    expect(wrapper.emitted('comment')?.[0]).toEqual([{ day: DAY, patch: { header: 'New title' } }])
  })

  it('opens the notes band expanded and still lets it be closed', async () => {
    // Open by default: the comment is what a day is read THROUGH, and people
    // expanded it every time anyway. It can still be collapsed.
    const wrapper = mountTable()

    expect(wrapper.find('.comment-input').exists()).toBe(true)

    await wrapper.find('.comment-toggle').trigger('click')

    expect(wrapper.find('.comment-input').exists()).toBe(false)
  })

  it('gives a day note ten rows to be written in', () => {
    // Two rows held the first line of a note; the rest had to be read by
    // scrolling inside the field.
    const wrapper = mountTable()

    expect(wrapper.find('.comment-input').attributes('rows')).toBe('10')
  })
})

describe('the ribbon width', () => {
  // main.css sizes the table so `--matrix-per-screen` day sections fill the
  // card. Left at two, a one-day period filled half of it.
  const perScreen = (wrapper) => wrapper.find('.app-datatable--matrix').attributes('style')

  it('gives a one-day period the whole width', () => {
    expect(perScreen(mountTable())).toContain('--matrix-per-screen: 1')
  })

  it('fits two days a screen once the period has them', () => {
    const days = [
      { iso: '2026-07-19', label: '19 Jul 2026' },
      { iso: DAY, label: '20 Jul 2026' },
    ]

    expect(perScreen(mountTable({}, { days }))).toContain('--matrix-per-screen: 2')
  })
})
