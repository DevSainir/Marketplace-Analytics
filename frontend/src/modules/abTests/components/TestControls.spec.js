/**
 * The test's own controls — which transitions a seller is offered, and in which
 * state.
 *
 * "Finish" is the case worth pinning. It used to exist only in the API, so a
 * paused test could not be closed from the page at all.
 */
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import TestControls from '@/modules/abTests/components/TestControls.vue'

function build(status, extra = {}, test = {}) {
  return mount(TestControls, {
    props: { test: { status, variants: [{ variant_id: 'v1' }], ...test }, ...extra },
  })
}

describe('finishing a test', () => {
  it.each(['running', 'paused'])('is offered while the test is %s', (status) => {
    expect(build(status).find('[data-testid="finish"]').exists()).toBe(true)
  })

  it.each(['draft', 'cancelled', 'completed'])('is not offered to a %s test', (status) => {
    expect(build(status).find('[data-testid="finish"]').exists()).toBe(false)
  })

  it('asks the view for the finish rather than finishing', async () => {
    // Which photo the card keeps is decided in the dialog the view opens, so
    // the button must not emit a status change of its own.
    const wrapper = build('paused')

    await wrapper.get('[data-testid="finish"]').trigger('click')

    expect(wrapper.emitted('finish')).toHaveLength(1)
    expect(wrapper.emitted('status')).toBeUndefined()
  })
})

describe('starting a test the advertising paused', () => {
  it('asks first, because the next pass would pause it again', async () => {
    const wrapper = build('paused', {}, { paused_by_ads: true })
    const button = wrapper.get('[data-testid="start"]')

    await button.trigger('click')
    expect(wrapper.emitted('status')).toBeUndefined()
    expect(button.text()).toBe('No ads running — start anyway?')

    await button.trigger('click')
    expect(wrapper.emitted('status')).toEqual([['running']])
  })

  it('starts at once when the seller paused it', async () => {
    const wrapper = build('paused')

    await wrapper.get('[data-testid="start"]').trigger('click')

    expect(wrapper.emitted('status')).toEqual([['running']])
  })
})
