import { mount } from '@vue/test-utils'

import SessionList from '@/modules/profile/components/SessionList.vue'

/**
 * Every browser this account is signed in on.
 *
 * The User-Agent is parsed here and nowhere else: the server stores it raw
 * because parsing is presentation and changes with every browser release. The
 * rule that matters is what happens to a string the parser does not recognise
 * — it must read as «Неизвестное устройство», never as a confident guess about
 * a device somebody is deciding whether to trust.
 *
 * The current session is separated and never offered a «Завершить» in the list
 * of others: you cannot decide about the rest until you know which one is you,
 * and an accidental press there is a sign-out with no warning.
 */
const CHROME_MAC =
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36'
const SAFARI_IPHONE =
  'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1 Version/18.0 Mobile Safari/604.1'

function session(overrides = {}) {
  return {
    family_id: 'f-1',
    user_agent: CHROME_MAC,
    ip_address: '203.0.113.7',
    started_at: '2026-09-10T10:00:00Z',
    last_seen_at: '2026-09-14T10:00:00Z',
    is_current: false,
    ...overrides,
  }
}

function mountList(sessions) {
  return mount(SessionList, { props: { sessions, loading: false, busy: null } })
}

describe('SessionList — naming a device', () => {
  it('reads a browser and an OS out of the string', () => {
    const wrapper = mountList([session({ is_current: true })])

    expect(wrapper.text()).toContain('Chrome на macOS')
  })

  it('does not let Chrome’s Safari claim win', () => {
    // Every Chromium UA ends «Safari/537.36», and Edge and Opera both claim
    // Chrome. Order in the table is the whole implementation.
    const wrapper = mountList([session({ user_agent: SAFARI_IPHONE, is_current: true })])

    expect(wrapper.text()).toContain('Safari на iOS')
  })

  it('says «неизвестное» rather than guessing', () => {
    const wrapper = mountList([session({ user_agent: 'curl/8.4.0', is_current: true })])

    expect(wrapper.text()).toContain('Неизвестное устройство')
  })

  it('says so when the row predates the provenance columns', () => {
    // Nullable on purpose: inventing an address would put a fiction in a list
    // people use to decide whether they have been broken into.
    const wrapper = mountList([session({ user_agent: null, ip_address: null, is_current: true })])

    expect(wrapper.text()).toContain('Неизвестное устройство')
    expect(wrapper.text()).toContain('адрес не записан')
  })
})

describe('SessionList — deciding about the others', () => {
  it('separates the session doing the reading and offers it no «Завершить»', () => {
    const wrapper = mountList([
      session({ family_id: 'mine', is_current: true }),
      session({ family_id: 'phone' }),
    ])
    const current = wrapper.find('.pf-session.is-current')

    expect(current.text()).toContain('сейчас здесь')
    expect(current.findAll('button')).toHaveLength(0)
  })

  it('emits the lineage to end, not its position in the list', async () => {
    const wrapper = mountList([
      session({ family_id: 'mine', is_current: true }),
      session({ family_id: 'phone' }),
    ])

    const button = () =>
      wrapper.findAll('button').find((b) => ['Sign out', 'Really sign out?'].includes(b.text()))
    await button().trigger('click')
    await button().trigger('click')

    expect(wrapper.emitted('end')).toEqual([['phone']])
  })

  it('asks before signing a device out', async () => {
    // Ending a session is not undoable from here: the first press only asks.
    const wrapper = mountList([
      session({ family_id: 'mine', is_current: true }),
      session({ family_id: 'phone' }),
    ])

    const end = wrapper.findAll('button').find((b) => b.text() === 'Sign out')
    await end.trigger('click')

    expect(wrapper.emitted('end')).toBeUndefined()
    expect(end.text()).toBe('Really sign out?')
  })

  it('offers nothing to end when there is nothing else', () => {
    const wrapper = mountList([session({ is_current: true })])

    expect(wrapper.text()).toContain('Больше нигде не выполнен вход')
    expect(wrapper.findAll('button')).toHaveLength(0)
  })
})
