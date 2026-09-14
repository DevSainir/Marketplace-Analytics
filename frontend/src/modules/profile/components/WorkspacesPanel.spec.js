import { mount } from '@vue/test-utils'

import WorkspacesPanel from '@/modules/profile/components/WorkspacesPanel.vue'

/**
 * The merged workspaces block.
 *
 * «Кабинет» and «Управление кабинетами» listed the same
 * workspaces twice — one copy to switch between, one to administer — so every
 * name appeared twice and each carried different buttons.
 *
 * The risk in merging them is `canManage`. Switching belongs to everybody: the
 * whole app is scoped to the chosen workspace, and a manager who cannot change
 * it is stuck in one. Creating, deleting and WB tokens belong to an owner,
 * matching `_owner_only` on those routes. Collapse the two and forget the
 * distinction, and every manager gets a delete button.
 */
const WORKSPACES = [
  { id: 'ws-1', name: 'ИП Первый', is_primary: true },
  { id: 'ws-2', name: 'ИП Второй', is_primary: false },
]

function mountPanel(props = {}) {
  return mount(WorkspacesPanel, {
    props: { workspaces: WORKSPACES, currentId: 'ws-1', canManage: true, ...props },
    global: { stubs: { WorkspaceTokensForm: true } },
  })
}

const labels = (wrapper) => wrapper.findAll('button').map((b) => b.text())

describe('WorkspacesPanel', () => {
  it('offers no switch for the workspace already in use', () => {
    // A button that does nothing is worse than no button: it invites a click
    // and a full page reload for no change.
    const wrapper = mountPanel()
    const [active, other] = wrapper.findAll('li')

    expect(active.text()).toContain('Активно')
    expect(active.text()).not.toContain('Переключить')
    expect(other.text()).toContain('Переключить')
  })

  it('puts every action for one workspace on that workspace’s row', () => {
    const wrapper = mountPanel()
    const other = wrapper.findAll('li')[1]

    expect(other.text()).toContain('Переключить')
    expect(other.text()).toContain('Токены WB')
    expect(other.text()).toContain('Удалить')
  })

  it('emits the workspace being switched to', async () => {
    const wrapper = mountPanel()

    await wrapper.findAll('li')[1].findAll('button')[0].trigger('click')

    expect(wrapper.emitted('select')).toEqual([['ws-2']])
  })

  it('gives a MANAGER the switch and nothing else', () => {
    // The assertion this whole merge rests on.
    const wrapper = mountPanel({ canManage: false })

    expect(labels(wrapper)).toEqual(['Переключить'])
    expect(wrapper.find('input[type="text"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Токены WB')
    expect(wrapper.text()).not.toContain('Удалить')
  })

  it('does not delete a workspace on the first press', async () => {
    // It hides every SKU underneath it.
    const wrapper = mountPanel()
    const remove = wrapper.findAll('li')[1].findAll('button')[2]

    await remove.trigger('click')

    expect(wrapper.emitted('remove')).toBeUndefined()
    expect(remove.text()).toBe('Точно удалить?')
  })

  it('deletes on the second press', async () => {
    const wrapper = mountPanel()
    const remove = wrapper.findAll('li')[1].findAll('button')[2]

    await remove.trigger('click')
    await remove.trigger('click')

    expect(wrapper.emitted('remove')).toEqual([['ws-2']])
  })

  it('creates from the field above the list, and clears it', async () => {
    const wrapper = mountPanel()

    await wrapper.find('input[type="text"]').setValue('  ИП Третий  ')
    await wrapper.find('form').trigger('submit.prevent')

    expect(wrapper.emitted('create')).toEqual([['ИП Третий']])
    expect(wrapper.find('input[type="text"]').element.value).toBe('')
  })

  it('says so when there is nothing to list', () => {
    const wrapper = mountPanel({ workspaces: [] })

    expect(wrapper.text()).toContain('Пока нет ни одного кабинета')
  })
})
