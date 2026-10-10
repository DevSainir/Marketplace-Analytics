import { mount } from '@vue/test-utils'
import { reactive } from 'vue'
import { routeLocationKey } from 'vue-router'

import AppHeaderNext from '@/core/components/AppHeaderNext.vue'

function mountHeader(props = {}) {
  return mount(AppHeaderNext, {
    props,
    global: {
      // The header follows the route to keep the active link in view; a bare
      // location is all it reads.
      provide: { [routeLocationKey]: reactive({ path: '/' }) },
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

/** The nav labels the header actually renders. */
const labels = (wrapper) => wrapper.findAll('nav a').map((link) => link.text())

describe('a page built from two module grants', () => {
  it('is advertised only when both are granted', () => {
    const wrapper = mountHeader({
      isAuthenticated: true,
      authResolved: true,
      modules: ['monitoring', 'finreports'],
    })

    expect(labels(wrapper)).toContain('Сводка')
  })

  it('stays hidden when one of the two is withheld', () => {
    const wrapper = mountHeader({
      isAuthenticated: true,
      authResolved: true,
      modules: ['monitoring'],
    })

    expect(labels(wrapper)).not.toContain('Сводка')
  })
})

describe('«Реклама»', () => {
  it('is offered to any subscriber who holds the «Реклама» grant', () => {
    const wrapper = mountHeader({
      isAuthenticated: true,
      authResolved: true,
      internalFeatures: false,
      modules: ['advertising'],
    })

    expect(labels(wrapper)).toContain('Реклама')
  })

  it('is not offered on «Мониторинг» alone', () => {
    const wrapper = mountHeader({
      isAuthenticated: true,
      authResolved: true,
      internalFeatures: true,
      modules: ['monitoring', 'finreports'],
    })

    expect(labels(wrapper)).not.toContain('Реклама')
  })
})
