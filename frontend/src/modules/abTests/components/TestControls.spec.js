/**
 * The test's own controls — which transitions a seller is offered, and in which
 * state.
 *
 * «Завершить» is the case worth pinning. It used to exist only in the API, so a
 * paused test could not be closed from the page at all.
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

  it('asks the view for the finish rather than finishing', async () => {
    // Which photo the card keeps is decided in the dialog the view opens, so
    // the button must not emit a status change of its own.
    const wrapper = build('paused')

    await wrapper.get('[data-testid="finish"]').trigger('click')

    expect(wrapper.emitted('finish')).toHaveLength(1)
    expect(wrapper.emitted('status')).toBeUndefined()
  })
})
