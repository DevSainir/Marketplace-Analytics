import { mount } from '@vue/test-utils'

import WorkspaceMenu from '@/core/components/WorkspaceMenu.vue'

describe('WorkspaceMenu', () => {
  it('marks a кабинет opened read-only from another organisation', async () => {
    const wrapper = mount(WorkspaceMenu, {
      props: {
        workspaces: [
          { id: 'own', name: 'Демо', is_guest: false },
          { id: 'guest', name: 'NEVA', is_guest: true },
        ],
        currentId: 'own',
      },
    })

    await wrapper.find('button').trigger('click')
    const rows = wrapper.findAll('[role="option"]').map((row) => row.text())

    expect(rows[0]).not.toContain('просмотр')
    expect(rows[1]).toContain('NEVA')
    expect(rows[1]).toContain('просмотр')
  })
})
