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
  it('does NOT show "Sign in" while auth is still resolving (no flash)', () => {
    // status 'unknown' → authResolved false: a full reload (e.g. a workspace
    // switch) must not flash the guest state before the silent refresh confirms
    // the session.
    const text = mountHeader({ isAuthenticated: false, authResolved: false }).text()

    expect(text).not.toContain('Sign in')
  })

  it('shows "Sign in" once auth resolves to guest', () => {
    const text = mountHeader({ isAuthenticated: false, authResolved: true }).text()

    expect(text).toContain('Sign in')
  })

  it('shows the workspace/profile cluster, not "Sign in", when authenticated', () => {
    const wrapper = mountHeader({
      isAuthenticated: true,
      authResolved: true,
      userEmail: 'seller@example.com',
      workspaces: [{ id: 'w1', name: 'Demo' }],
      currentWorkspaceId: 'w1',
    })

    expect(wrapper.find('[aria-label="Profile"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="workspace"]').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('Sign in')
  })
})

/** The nav labels the header actually renders. */
const labels = (wrapper) => wrapper.findAll('nav a').map((link) => link.text())

describe('each page is a grant of its own', () => {
  it('advertises Summary on its own grant alone', () => {
    const wrapper = mountHeader({ isAuthenticated: true, authResolved: true, modules: ['summary'] })

    expect(labels(wrapper)).toEqual(['Home', 'Summary'])
  })

  it('no longer opens Summary on Monitoring and P&L together', () => {
    const wrapper = mountHeader({
      isAuthenticated: true,
      authResolved: true,
      modules: ['monitoring', 'finreports'],
    })

    expect(labels(wrapper)).not.toContain('Summary')
  })

  it('advertises Heatmap on its own grant alone', () => {
    const wrapper = mountHeader({ isAuthenticated: true, authResolved: true, modules: ['heatmap'] })

    expect(labels(wrapper)).toEqual(['Home', 'Heatmap'])
  })

  it('no longer opens Heatmap on Monitoring', () => {
    const wrapper = mountHeader({
      isAuthenticated: true,
      authResolved: true,
      modules: ['monitoring'],
    })

    expect(labels(wrapper)).not.toContain('Heatmap')
  })
})

describe('Advertising', () => {
  it('is offered to any subscriber who holds the Advertising grant', () => {
    const wrapper = mountHeader({
      isAuthenticated: true,
      authResolved: true,
      modules: ['advertising'],
    })

    expect(labels(wrapper)).toContain('Advertising')
  })

  it('is not offered on Monitoring alone', () => {
    const wrapper = mountHeader({
      isAuthenticated: true,
      authResolved: true,
      modules: ['monitoring', 'finreports'],
    })

    expect(labels(wrapper)).not.toContain('Advertising')
  })
})
