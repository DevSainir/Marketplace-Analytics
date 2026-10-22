import { mount } from '@vue/test-utils'

import PeriodSelector from '@/core/components/PeriodSelector.vue'
import { isoDaysAgo } from '@/core/utils/dates'

/** Mounted with a window a fortnight wide, so a preset visibly changes it. */
function mountPicker(props = {}) {
  return mount(PeriodSelector, {
    props: { from: '2026-01-01', to: '2026-01-14', ...props },
  })
}

/** Open the popover — the presets live in its footer. */
async function openCalendar(wrapper) {
  await wrapper.find('button').trigger('click')
  return wrapper
}

const preset = (wrapper, label) =>
  wrapper.findAll('.preset-btn').find((button) => button.text() === label)

describe('PeriodSelector', () => {
  it('applies a preset at once instead of leaving it drafted', async () => {
    // Clicking "30 days" is a finished decision: there is no second half of the
    // gesture to wait for, so the page must not sit on the old window until
    // "Apply" is pressed as well.
    const wrapper = await openCalendar(mountPicker())

    await preset(wrapper, '30 days').trigger('click')

    expect(wrapper.emitted('update:from')[0]).toEqual([isoDaysAgo(29)])
    expect(wrapper.emitted('update:to')[0]).toEqual([isoDaysAgo(0)])
    expect(wrapper.emitted('apply')).toHaveLength(1)
  })

  it('emits the window before the apply, so a listener reads the new one', async () => {
    // The monitoring page's handler reads the dates back off its own refs; the
    // other order would have it push the window the preset just replaced.
    const wrapper = await openCalendar(mountPicker())

    await preset(wrapper, '7 days').trigger('click')

    // `emitted()` keys are in first-emission order, so «last key» is «last event».
    expect(Object.keys(wrapper.emitted()).at(-1)).toBe('apply')
  })

  it('counts the preset end day as one of the N', async () => {
    // "7 days" ending on the 10th is the 4th to the 10th, not the 3rd to the
    // 10th — the caller's last settled day is a day of the window.
    const wrapper = await openCalendar(mountPicker({ presetEnd: '2026-03-10' }))

    await preset(wrapper, '7 days').trigger('click')

    expect(wrapper.emitted('update:from')[0]).toEqual(['2026-03-04'])
    expect(wrapper.emitted('update:to')[0]).toEqual(['2026-03-10'])
  })

  it('offers "All time" in place of "180 days" when the page knows its first day', async () => {
    // A page whose data has no window limit (advertising: WB keeps a campaign's
    // whole life) opts in by passing its first day; every other page keeps the
    // stock presets.
    const wrapper = await openCalendar(
      mountPicker({ presetEnd: '2026-10-04', historyFrom: '2023-10-24' }),
    )

    await preset(wrapper, 'All time').trigger('click')

    expect(preset(wrapper, '180 days')).toBeUndefined()
    expect(wrapper.emitted('range')[0]).toEqual([{ from: '2023-10-24', to: '2026-10-04' }])
  })

  it('keeps the stock presets for a page that names no first day', async () => {
    const wrapper = await openCalendar(mountPicker())

    expect(preset(wrapper, '180 days')).toBeDefined()
    expect(preset(wrapper, 'All time')).toBeUndefined()
  })

  it('marks the preset whose window is on screen, and only that one', async () => {
    // A page that opened on, or was set to, "30 days" must read as "30 days"
    // when the picker is opened again.
    const wrapper = await openCalendar(
      mountPicker({ from: '2026-02-09', to: '2026-03-10', presetEnd: '2026-03-10' }),
    )

    const active = wrapper.findAll('.preset-btn--active').map((button) => button.text())
    expect(active).toEqual(['30 days'])
  })

  it('marks "All time" when the window runs from the first day', async () => {
    const wrapper = await openCalendar(
      mountPicker({
        from: '2023-10-24',
        to: '2026-10-04',
        presetEnd: '2026-10-04',
        historyFrom: '2023-10-24',
      }),
    )

    expect(preset(wrapper, 'All time').classes()).toContain('preset-btn--active')
  })

  it('marks nothing for a hand-picked range', async () => {
    const wrapper = await openCalendar(mountPicker())

    expect(wrapper.findAll('.preset-btn--active')).toHaveLength(0)
  })

  it('applies a hand-picked range on its second click', async () => {
    // The second click is the whole decision, the same way a preset is. The
    // popover closing with nothing happening read as a control that had not
    // worked, and the button that would have finished the job is a screen away
    // by the time the calendar is open.
    const wrapper = await openCalendar(mountPicker())
    const days = wrapper.findAll('.day:not([disabled])')

    await days[0].trigger('click')
    await days[5].trigger('click')

    expect(wrapper.emitted('update:from')).toHaveLength(1)
    expect(wrapper.emitted('apply')).toHaveLength(1)
  })

  it('applies nothing on the FIRST click, while the range is still half-made', async () => {
    const wrapper = await openCalendar(mountPicker())

    await wrapper.findAll('.day:not([disabled])')[0].trigger('click')

    expect(wrapper.emitted('apply')).toBeUndefined()
  })

  it("greys out the days before the page's first day", async () => {
    // A day with no data behind it is refused by the calendar itself, not by
    // the page after the window was picked.
    const wrapper = await openCalendar(mountPicker({ historyFrom: '2026-01-10' }))
    const january = wrapper.findAll('.calendar-grid')[1]

    const firstEnabled = january.findAll('.day:not([disabled])')[0]

    expect(firstEnabled.text()).toBe('10')
  })

  it('holds the second click within the longest window the page answers for', async () => {
    const wrapper = await openCalendar(mountPicker({ max: '2026-01-31', maxDays: 3 }))
    const january = () => wrapper.findAll('.calendar-grid')[1]
    // January 2026 starts on a Thursday: three leading December days, then the 1st.
    await january().findAll('.day')[3 + 4].trigger('click') // the 5th

    const enabled = january()
      .findAll('.day')
      .slice(3, 3 + 31)
      .filter((day) => day.attributes('disabled') === undefined)
      .map((day) => day.text())

    expect(enabled).toEqual(['3', '4', '5', '6', '7'])
  })
})
