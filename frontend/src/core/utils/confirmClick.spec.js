import { mount } from '@vue/test-utils'
import { defineComponent } from 'vue'

import { CONFIRM_RESET_MS, confirmLabel, useConfirmClick } from '@/core/utils/confirmClick'

/** The composable inside a component, the only place its unmount hook may live. */
function host() {
  let api
  mount(
    defineComponent({
      setup() {
        api = useConfirmClick()
        return () => null
      },
    }),
  )
  return api
}

describe('confirmClick', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('acts only on the second press of the same control', () => {
    const confirm = host()
    const action = vi.fn()

    confirm.press('row-1', action)
    confirm.press('row-1', action)

    expect(action).toHaveBeenCalledTimes(1)
  })

  it('withdraws the first question when another control is armed', () => {
    // A stray press elsewhere must never confirm what the reader left behind.
    const confirm = host()
    const action = vi.fn()

    confirm.press('row-1', action)
    confirm.press('row-2', action)

    expect(action).not.toHaveBeenCalled()
    expect(confirm.isArmed('row-1')).toBe(false)
  })

  it('withdraws an unanswered question by itself', () => {
    const confirm = host()

    confirm.press('row-1', vi.fn())
    vi.advanceTimersByTime(CONFIRM_RESET_MS)

    expect(confirm.isArmed('row-1')).toBe(false)
  })

  it("asks in the button's own words", () => {
    expect(confirmLabel('Delete test')).toBe('Really delete test?')
  })
})
