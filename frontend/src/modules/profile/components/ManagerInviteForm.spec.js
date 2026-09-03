import { mount } from '@vue/test-utils'

import ManagerInviteForm from '@/modules/profile/components/ManagerInviteForm.vue'

/**
 * What an owner is handed after issuing an invitation.
 *
 * This suite exists because the form used to show the raw token under the words
 * «Ссылка показывается один раз». It was not a link, and there was nowhere for
 * the recipient to put a bare token — the accept screen did not exist. An owner
 * looking at it could not tell what they were supposed to send, or to where.
 */
function issueThrough(wrapper, invitation) {
  // The parent hands the created invitation back through `onIssued`; this is
  // the same call the profile view makes.
  const [payload] = wrapper.emitted('invite') ?? [[]]
  payload[0].onIssued(invitation)
  return wrapper.vm.$nextTick()
}

describe('ManagerInviteForm — the value it hands the owner', () => {
  it('renders a followable link, not the bare token', async () => {
    const wrapper = mount(ManagerInviteForm, {
      global: { stubs: { AccessGrantFields: true } },
    })
    await wrapper.find('form').trigger('submit.prevent')
    await issueThrough(wrapper, { token: 'raw-token-value' })

    const shown = wrapper.find('code').text()
    expect(shown).toBe(`${window.location.origin}/invite?token=raw-token-value`)
    // The token is still in there — it has to be — but never on its own.
    expect(shown).not.toBe('raw-token-value')
  })

  it('escapes a token that would otherwise break the query string', async () => {
    // Tokens are URL-safe base64 today, which is exactly the kind of thing that
    // stops being true quietly.
    const wrapper = mount(ManagerInviteForm, {
      global: { stubs: { AccessGrantFields: true } },
    })
    await wrapper.find('form').trigger('submit.prevent')
    await issueThrough(wrapper, { token: 'a+b/c=d&e' })

    expect(wrapper.find('code').text()).toContain('token=a%2Bb%2Fc%3Dd%26e')
  })
})
