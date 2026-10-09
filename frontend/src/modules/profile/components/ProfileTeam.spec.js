import { mount } from '@vue/test-utils'

import ProfileTeam from '@/modules/profile/components/ProfileTeam.vue'

/**
 * The roster.
 *
 * Removing is what actually withdraws access from somebody who has already
 * joined — revoking their invitation does not — so it cannot be undone from
 * this screen and asks twice. The arming is PER ROW: a confirm that armed the
 * whole list would put «Точно удалить?» under a name nobody meant to touch.
 *
 * The grant editor is a drawer now, so this component states a grant and asks
 * the parent to open it. That is what makes the list stay a list: the old panel
 * rendered four controls under every manager, and its height grew with the
 * team.
 */
const MANAGERS = [
  {
    user_id: 'u-1',
    email: 'first@example.com',
    role: 'manager',
    joined_at: '2026-09-02T00:00:00Z',
    access_level: 'read_write',
    modules: ['monitoring', 'finreports'],
  },
  {
    user_id: 'u-2',
    email: 'second@example.com',
    role: 'manager',
    joined_at: '2026-09-03T00:00:00Z',
    access_level: 'read_only',
    modules: [],
  },
]

function mountPanel(props = {}) {
  return mount(ProfileTeam, {
    props: { managers: MANAGERS, canInvite: true, ...props },
  })
}

const rows = (wrapper) => wrapper.findAll('.pf-grid__row')
const button = (row, label) => row.findAll('button').find((b) => b.text() === label)

describe('ProfileTeam', () => {
  it('states each manager’s grant instead of rendering a form per row', () => {
    const wrapper = mountPanel()
    const [first, second] = rows(wrapper)

    expect(first.text()).toContain('Чтение и запись')
    expect(first.text()).toContain('Мониторинг')
    expect(second.text()).toContain('Только чтение')
    // A grant of nothing is a state worth naming — it looks identical to a
    // loading row otherwise.
    expect(second.text()).toContain('нет доступа')
  })

  it('asks the parent to open the drawer for one manager', async () => {
    const wrapper = mountPanel()

    await button(rows(wrapper)[1], 'Доступ').trigger('click')

    expect(wrapper.emitted('edit')).toEqual([[MANAGERS[1]]])
  })

  it('does NOT remove on the first press', async () => {
    const wrapper = mountPanel()
    const remove = button(rows(wrapper)[0], 'Удалить')

    await remove.trigger('click')

    expect(wrapper.emitted('remove')).toBeUndefined()
    expect(remove.text()).toBe('Точно удалить?')
  })

  it('emits the manager on the second press', async () => {
    const wrapper = mountPanel()
    const remove = button(rows(wrapper)[0], 'Удалить')

    await remove.trigger('click')
    await remove.trigger('click')

    expect(wrapper.emitted('remove')).toEqual([['u-1']])
  })

  it('asks again per manager rather than arming the whole list', async () => {
    // Otherwise «Точно удалить?» appears under a name nobody meant to touch.
    const wrapper = mountPanel()

    await button(rows(wrapper)[0], 'Удалить').trigger('click')

    expect(button(rows(wrapper)[1], 'Удалить').text()).toBe('Удалить')
  })

  it('says so when there is nobody to configure', () => {
    const wrapper = mountPanel({ managers: [] })

    expect(wrapper.text()).toContain('В организации пока нет менеджеров')
  })

  it('offers no invitation to somebody who may not issue one', () => {
    const wrapper = mountPanel({ canInvite: false })

    expect(wrapper.text()).not.toContain('Пригласить менеджера')
  })
})
