import { mount } from '@vue/test-utils'

import AppHeaderNext from '@/core/components/AppHeaderNext.vue'

function mountHeader(props = {}) {
  return mount(AppHeaderNext, {
    props,
    global: {
      stubs: {
        RouterLink: { template: '<a><slot /></a>' },
        // The switcher is a component of its own with its own spec; this suite
        // is about which cluster the header renders, not what is inside it.
        WorkspaceMenu: { template: '<div data-test="workspace" />' },
      },
    },
  })
}

describe('AppHeaderNext auth zone', () => {
  it('does NOT show «Войти» while auth is still resolving (no flash)', () => {
    // status 'unknown' → authResolved false: a full reload (e.g. a workspace
    // switch) must not flash the guest state before the silent refresh confirms
    // the session.
    const text = mountHeader({ isAuthenticated: false, authResolved: false }).text()

    expect(text).not.toContain('Войти')
  })

  it('shows «Войти» once auth resolves to guest', () => {
    const text = mountHeader({ isAuthenticated: false, authResolved: true }).text()

    expect(text).toContain('Войти')
  })

  it('shows the workspace/profile cluster, not «Войти», when authenticated', () => {
    const wrapper = mountHeader({
      isAuthenticated: true,
      authResolved: true,
      userEmail: 'seller@example.com',
      workspaces: [{ id: 'w1', name: 'Демо' }],
      currentWorkspaceId: 'w1',
    })

    expect(wrapper.find('[aria-label="Профиль"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="workspace"]').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('Войти')
  })
})
