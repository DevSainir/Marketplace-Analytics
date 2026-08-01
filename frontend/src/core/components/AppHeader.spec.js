import { mount } from '@vue/test-utils'

import AppHeader from '@/core/components/AppHeader.vue'

function mountHeader(props = {}) {
  return mount(AppHeader, {
    props,
    global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } },
  })
}

describe('AppHeader auth zone', () => {
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
  })
})
