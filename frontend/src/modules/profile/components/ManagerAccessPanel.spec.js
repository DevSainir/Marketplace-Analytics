import { mount } from '@vue/test-utils'

import ManagerAccessPanel from '@/modules/profile/components/ManagerAccessPanel.vue'

/** One manager with the grant every pre-existing membership was backfilled to. */
function manager(overrides = {}) {
  return {
    user_id: 'u-1',
    email: 'manager@example.com',
    role: 'manager',
    joined_at: '2026-08-01T10:00:00Z',
    access_level: 'read_write',
    modules: ['monitoring', 'finreports', 'ab_tests'],
    ...overrides,
  }
}

function mountPanel(managers = [manager()]) {
  return mount(ManagerAccessPanel, { props: { managers, saving: null } })
}

const saveButton = (wrapper) =>
  wrapper.findAll('button').find((button) => button.text().startsWith('Сохранить'))

const moduleSwitch = (wrapper, index) => wrapper.findAll('input[type="checkbox"]')[index]

describe('ManagerAccessPanel', () => {
  it('does not offer to save a grant nobody has changed', () => {
    // A save button that is always live invites an owner to re-send the state
    // they are already looking at, and every such request is a chance to write
    // a stale form over a change made elsewhere.
    const wrapper = mountPanel()

    expect(saveButton(wrapper).attributes('disabled')).toBeDefined()
  })

  it('stages a toggle instead of saving on every flip', async () => {
    // Setting up one person is three or four gestures. Saving each would fire
    // that many requests, and the intermediate ones are grants the owner never
    // meant to store.
    const wrapper = mountPanel()

    await moduleSwitch(wrapper, 1).setValue(false)

    expect(wrapper.emitted('save')).toBeUndefined()
    expect(saveButton(wrapper).attributes('disabled')).toBeUndefined()
  })

  it('sends the whole grant, not just what changed', async () => {
    // The endpoint replaces rather than patches, so a partial payload would
    // silently restore a module the owner had just switched off.
    const wrapper = mountPanel()

    await moduleSwitch(wrapper, 1).setValue(false)
    await saveButton(wrapper).trigger('click')

    expect(wrapper.emitted('save')[0][0]).toEqual({
      userId: 'u-1',
      grant: { accessLevel: 'read_write', modules: ['monitoring', 'ab_tests'] },
    })
  })

  it('carries the level through a module edit', async () => {
    // The two axes are independent; editing one must not reset the other.
    const wrapper = mountPanel([manager({ access_level: 'read_only' })])

    await moduleSwitch(wrapper, 0).setValue(false)
    await saveButton(wrapper).trigger('click')

    expect(wrapper.emitted('save')[0][0].grant.accessLevel).toBe('read_only')
  })

  it('says so when there is nobody to configure', () => {
    // An empty list with no words reads as a page that failed to load.
    const wrapper = mountPanel([])

    expect(wrapper.text()).toContain('пока нет менеджеров')
  })
})
