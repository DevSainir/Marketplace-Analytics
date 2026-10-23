import { mount } from '@vue/test-utils'

import ProfileWorkspaces from '@/modules/profile/components/ProfileWorkspaces.vue'

/**
 * The workspaces list.
 *
 * "Workspace" and "Manage workspaces" once listed the same accounts twice —
 * one copy to switch between, one to administer — so every name appeared twice
 * carrying different buttons. They are one list, and the risk in that is
 * `canManage`: choosing belongs to everybody, since the whole app is scoped to
 * the chosen workspace and a manager who cannot change it is stuck in one.
 * Creating, deleting and WB tokens belong to an owner, matching `_owner_only`
 * on those routes. Collapse the two and forget the distinction, and every
 * manager gets a delete button.
 *
 * The token editor moved to a drawer, so this component now only reports the
 * state — "0 of 13" — and asks the parent to open it. That count is the thing
 * the old accordion made impossible to see, so it is asserted here.
 */
const WORKSPACES = [
  { id: 'ws-1', name: 'First Shop', is_primary: true, created_at: '2026-08-14T00:00:00Z' },
  { id: 'ws-2', name: 'Second Shop', is_primary: false, created_at: '2026-08-21T00:00:00Z' },
]

function mountPanel(props = {}) {
  return mount(ProfileWorkspaces, {
    props: {
      workspaces: WORKSPACES,
      currentId: 'ws-1',
      canManage: true,
      tokenStatuses: {},
      ...props,
    },
  })
}

const labels = (wrapper) => wrapper.findAll('button').map((b) => b.text())
const rows = (wrapper) => wrapper.findAll('.pf-grid__row')

describe('ProfileWorkspaces', () => {
  it('offers no switch for the workspace already in use', () => {
    // A button that does nothing is worse than no button: it invites a click
    // and a full page reload for no change.
    const wrapper = mountPanel()
    const [active, other] = rows(wrapper)

    expect(active.text()).toContain('Current')
    expect(active.text()).not.toContain('Select')
    expect(other.text()).toContain('Select')
  })

  it('emits the workspace being switched to', async () => {
    const wrapper = mountPanel()

    await rows(wrapper)[1].findAll('button')[0].trigger('click')

    expect(wrapper.emitted('select')).toEqual([['ws-2']])
  })

  it('gives a MANAGER the choice and nothing else', () => {
    // The assertion the whole merge rests on.
    const wrapper = mountPanel({ canManage: false })

    expect(labels(wrapper)).toEqual(['Select'])
    expect(wrapper.find('input[type="text"]').exists()).toBe(false)
    // Not even the column: a manager cannot set a token, so a column of "—"
    // for them is a column that says nothing.
    expect(wrapper.text()).not.toContain('WB tokens')
  })

  it('does not delete a workspace on the first press', async () => {
    // It hides every SKU underneath it.
    const wrapper = mountPanel()
    const remove = rows(wrapper)[1].findAll('button').at(-1)

    await remove.trigger('click')

    expect(wrapper.emitted('remove')).toBeUndefined()
    expect(remove.text()).toBe('Really delete?')
  })

  it('deletes on the second press', async () => {
    const wrapper = mountPanel()
    const remove = rows(wrapper)[1].findAll('button').at(-1)

    await remove.trigger('click')
    await remove.trigger('click')

    expect(wrapper.emitted('remove')).toEqual([['ws-2']])
  })

  it('creates from the field above the list, and clears it', async () => {
    const wrapper = mountPanel()

    await wrapper.find('input[type="text"]').setValue('  Third Shop  ')
    await wrapper.find('form').trigger('submit.prevent')

    expect(wrapper.emitted('create')).toEqual([['Third Shop']])
    expect(wrapper.find('input[type="text"]').element.value).toBe('')
  })

  it('says on the row how many WB tokens are set', () => {
    // The question the list exists to answer. The primary workspace takes one
    // token per WB API category — thirteen — and every other takes one.
    const wrapper = mountPanel({
      tokenStatuses: {
        'ws-1': { configured: ['content', 'statistics'] },
        'ws-2': { configured: [] },
      },
    })

    expect(rows(wrapper)[0].text()).toContain('2 of 13')
    expect(rows(wrapper)[1].text()).toContain('0 of 1')
  })

  it('asks the parent to open the token drawer rather than editing in place', async () => {
    const wrapper = mountPanel({ tokenStatuses: { 'ws-2': { configured: [] } } })
    const tokens = rows(wrapper)[1]
      .findAll('button')
      .find((b) => b.text() === 'Tokens')

    await tokens.trigger('click')

    expect(wrapper.emitted('tokens')).toEqual([[WORKSPACES[1]]])
  })

  it('says so when there is nothing to list', () => {
    const wrapper = mountPanel({ workspaces: [] })

    expect(wrapper.text()).toContain('No workspaces yet')
  })
})
