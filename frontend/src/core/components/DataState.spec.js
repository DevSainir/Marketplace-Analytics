import { mount } from '@vue/test-utils'

import DataState from '@/core/components/DataState.vue'

describe('DataState', () => {
  it('says what failed and why, in one look on every page', () => {
    const wrapper = mount(DataState, { props: { kind: 'error', text: "Can't reach the server." } })

    expect(wrapper.text()).toContain("Couldn't load")
    expect(wrapper.text()).toContain("Can't reach the server.")
  })

  it('reports a failure above figures that stay, without claiming a load failed', () => {
    // The same line carries a failed save (a balance mark, an exclusion), so
    // it gives the reason only.
    const wrapper = mount(DataState, {
      props: { kind: 'error', layout: 'line', text: "Couldn't save the mark" },
    })

    expect(wrapper.text()).toBe("Couldn't save the mark")
  })

  it('uses the one wording for an empty period unless the page has its own', () => {
    expect(mount(DataState, { props: { kind: 'empty' } }).text()).toBe(
      'No data for the selected period',
    )
  })

  it('says "Loading…" for every first load', () => {
    expect(mount(DataState, { props: { kind: 'loading' } }).text()).toContain('Loading…')
  })
})
