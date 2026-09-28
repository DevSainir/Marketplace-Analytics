/**
 * The test's own controls — which transitions a seller is offered, and in which
 * state.
 *
 * «Завершить» is the case worth pinning. It used to exist only in the API, so a
 * paused test could not be closed from the page at all; and it cannot be undone,
 * so a single stray press must not reach the store.
 */
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import TestControls from '@/modules/abTests/components/TestControls.vue'

function build(status, extra = {}) {
  return mount(TestControls, {
    props: { test: { status, variants: [{ variant_id: 'v1' }] }, ...extra },
  })
}

describe('finishing a test', () => {
  it.each(['running', 'paused'])('is offered while the test is %s', (status) => {
    expect(build(status).find('[data-testid="finish"]').exists()).toBe(true)
  })

  it.each(['draft', 'cancelled', 'completed'])('is not offered to a %s test', (status) => {
    expect(build(status).find('[data-testid="finish"]').exists()).toBe(false)
  })

  it('asks before it finishes, and finishes on the second press', async () => {
    const wrapper = build('paused')
    const button = wrapper.get('[data-testid="finish"]')

    await button.trigger('click')
    expect(wrapper.emitted('status')).toBeUndefined()
    expect(button.text()).toBe('Точно завершить?')

    await button.trigger('click')
    expect(wrapper.emitted('status')).toEqual([['cancelled']])
  })

  it('forgets the question once the test changes state underneath it', async () => {
    const wrapper = build('running')
    await wrapper.get('[data-testid="finish"]').trigger('click')

    await wrapper.setProps({ test: { status: 'paused', variants: [{ variant_id: 'v1' }] } })

    expect(wrapper.get('[data-testid="finish"]').text()).toBe('Завершить')
  })
})
