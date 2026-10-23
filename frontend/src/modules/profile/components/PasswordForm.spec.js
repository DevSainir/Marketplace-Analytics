import { mount } from '@vue/test-utils'

import PasswordForm from '@/modules/profile/components/PasswordForm.vue'

/**
 * Changing the password from inside a session.
 *
 * The rules mirror `UserRegisterRequest` — at least 8 characters, one lower and
 * one upper — and are stated here as well as enforced there, so the form does
 * not let somebody submit a password it could have told them about. The API is
 * still the authority: this suite pins that the form refuses what the API would
 * refuse, never that the form is the check.
 *
 * The repeat field is not a security control. It catches a typo in a value that
 * is masked, before that typo becomes a password nobody knows.
 */
function mountForm(props = {}) {
  return mount(PasswordForm, { props: { saving: false, error: '', ...props } })
}

const inputs = (wrapper) => wrapper.findAll('.pf-pw__wrap input')
const submitButton = (wrapper) => wrapper.find('button[type="submit"]')

async function fill(wrapper, { current, next, repeat }) {
  const [a, b, c] = inputs(wrapper)
  await a.setValue(current)
  await b.setValue(next)
  await c.setValue(repeat)
}

describe('PasswordForm — what it refuses to send', () => {
  it('will not submit an empty form', () => {
    const wrapper = mountForm()

    expect(submitButton(wrapper).attributes('disabled')).toBeDefined()
  })

  it('will not submit a password that fails a rule the API enforces', async () => {
    const wrapper = mountForm()

    await fill(wrapper, { current: 'old-one', next: 'tolowercase', repeat: 'tolowercase' })

    expect(submitButton(wrapper).attributes('disabled')).toBeDefined()
  })

  it('will not submit while the repeat disagrees', async () => {
    const wrapper = mountForm()

    await fill(wrapper, { current: 'old-one', next: 'Horosho-2026', repeat: 'Horosho-202' })

    expect(submitButton(wrapper).attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('Passwords do not match')
  })

  it('will not submit the password that is already set', async () => {
    // A change has to change something. The API refuses it too; saying so here
    // saves a round trip and a 422.
    const wrapper = mountForm()

    await fill(wrapper, { current: 'Horosho-2026', next: 'Horosho-2026', repeat: 'Horosho-2026' })

    expect(submitButton(wrapper).attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('New password matches the current one')
  })
})

describe('PasswordForm — what it sends', () => {
  it('emits both halves, because the current password is what proves the caller', async () => {
    const wrapper = mountForm()

    await fill(wrapper, { current: 'old-one', next: 'Horosho-2026', repeat: 'Horosho-2026' })
    await wrapper.find('form').trigger('submit.prevent')

    expect(wrapper.emitted('submit')).toEqual([
      [{ currentPassword: 'old-one', newPassword: 'Horosho-2026' }],
    ])
  })

  it('renders the server’s refusal verbatim', async () => {
    // The API says which of several things went wrong — wrong current
    // password, a password in a public leak — and the form must not paraphrase.
    const wrapper = mountForm({ error: 'Current password is wrong.' })

    expect(wrapper.text()).toContain('Current password is wrong.')
  })

  it('clears the fields when the parent says the change landed', async () => {
    const wrapper = mountForm()
    await fill(wrapper, { current: 'old-one', next: 'Horosho-2026', repeat: 'Horosho-2026' })

    wrapper.vm.reset()
    await wrapper.vm.$nextTick()

    expect(inputs(wrapper).map((i) => i.element.value)).toEqual(['', '', ''])
  })
})

describe('PasswordForm — the eye', () => {
  it('reveals all three fields at once, whichever eye is pressed', async () => {
    // The value is the same in all three; three independent states would be
    // three things to reason about for one secret.
    const wrapper = mountForm()

    await wrapper.findAll('.pf-pw__eye')[2].trigger('click')

    expect(inputs(wrapper).map((i) => i.attributes('type'))).toEqual(['text', 'text', 'text'])
  })
})
