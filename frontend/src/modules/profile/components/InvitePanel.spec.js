import { mount } from '@vue/test-utils'

import InvitePanel from '@/modules/profile/components/InvitePanel.vue'

/**
 * What an owner is handed after issuing an invitation.
 *
 * This suite exists because the form used to show the raw token under the words
 * «Ссылка показывается один раз». It was not a link, and there was nowhere for
 * the recipient to put a bare token — the accept screen did not exist. An owner
 * looking at it could not tell what they were supposed to send, or where.
 */
const TOKEN = 'plain-token'

function mountPanel() {
  return mount(InvitePanel, { props: { saving: null } })
}

/** Drive the drawer's footer button, which lives in the parent. */
async function submit(wrapper, invitation = { token: TOKEN }) {
  wrapper.vm.submit()
  await wrapper.vm.$nextTick()
  const [payload] = wrapper.emitted('invite').at(-1)
  payload.onIssued(invitation)
  await wrapper.vm.$nextTick()
  return payload
}

describe('InvitePanel — the value it hands the owner', () => {
  it('renders a followable link, not the bare token', async () => {
    const wrapper = mountPanel()

    await submit(wrapper)

    const shown = wrapper.find('code').text()
    expect(shown).toContain('/invite?token=')
    expect(shown).not.toBe(TOKEN)
  })

  it('escapes a token that would otherwise break the query string', async () => {
    const wrapper = mountPanel()

    await submit(wrapper, { token: 'a+b/c=d' })

    expect(wrapper.find('code').text()).toContain('a%2Bb%2Fc%3Dd')
  })
})

describe('InvitePanel — the grant that travels with the link', () => {
  it('sends every section by default, so an invite is not silently empty', async () => {
    const wrapper = mountPanel()

    const payload = await submit(wrapper)

    expect(payload.accessLevel).toBe('read_write')
    expect(payload.modules).toEqual(['monitoring', 'finreports', 'ab_tests'])
  })

  it('sends no email as null rather than an empty string', async () => {
    // The endpoint distinguishes the two: null is a bare link, and an empty
    // string is an address that fails validation.
    const wrapper = mountPanel()

    const payload = await submit(wrapper)

    expect(payload.email).toBeNull()
  })
})
