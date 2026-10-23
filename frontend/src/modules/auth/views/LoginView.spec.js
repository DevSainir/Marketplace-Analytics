import { mount } from '@vue/test-utils'

import LoginView from '@/modules/auth/views/LoginView.vue'

/**
 * How many confirmation codes one signup causes.
 *
 * This suite exists for one shipped bug: `/register` mails a code itself, and
 * the view asked for another the moment it navigated to the code screen. Two
 * mails arrived seconds apart with different codes — and because issuing a code
 * INVALIDATES the previous one, the first mail's code was dead on arrival. A
 * person who typed the code from the first message they opened was told it was
 * wrong.
 *
 * A backend test cannot see this: both calls are legitimate on their own, and
 * the defect is entirely in which of them the view decides to make.
 */
const push = vi.fn()
vi.mock('vue-router', () => ({
  useRoute: () => ({ query: {} }),
  useRouter: () => ({ push }),
  RouterLink: { template: '<a><slot /></a>' },
}))

const auth = {
  loading: false,
  error: null,
  emailTaken: false,
  needsConfirmation: false,
  login: vi.fn(),
  register: vi.fn(),
  askForConfirmationCode: vi.fn(),
  clearError: vi.fn(),
}
vi.mock('@/modules/auth/store', () => ({ useAuthStore: () => auth }))

function mountView() {
  return mount(LoginView, {
    global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } },
  })
}

/** Fill the form and submit it in the given mode. */
async function submit(wrapper, { mode }) {
  if (mode === 'register') {
    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Sign up')
      .trigger('click')
  }
  await wrapper.find('input[type="email"]').setValue('new@example.com')
  await wrapper.find('form').trigger('submit.prevent')
}

describe('LoginView — how many codes one signup sends', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    auth.needsConfirmation = false
    auth.error = null
  })

  it('sends exactly ONE code for a fresh registration', async () => {
    // `/register` mails it. Asking again here is the bug this pins.
    auth.register.mockResolvedValue(true)

    await submit(mountView(), { mode: 'register' })

    expect(auth.register).toHaveBeenCalledTimes(1)
    expect(auth.askForConfirmationCode).not.toHaveBeenCalled()
    expect(push).toHaveBeenCalledWith(expect.objectContaining({ name: 'confirm-email' }))
  })

  it('sends exactly ONE code when a signup resumes an unconfirmed address', async () => {
    // `/register` no longer refuses that case — it resumes it and mails a code,
    // exactly as a fresh signup does. So this path must not ask for one either.
    auth.register.mockResolvedValue(true)

    await submit(mountView(), { mode: 'register' })

    expect(auth.askForConfirmationCode).not.toHaveBeenCalled()
  })

  it('asks for a code when login is refused as unconfirmed', async () => {
    // `/login` never mails one either.
    auth.login.mockImplementation(async () => {
      auth.needsConfirmation = true
      return false
    })

    await submit(mountView(), { mode: 'login' })

    expect(auth.askForConfirmationCode).toHaveBeenCalledTimes(1)
  })

  it('sends nothing when login simply fails', async () => {
    auth.login.mockResolvedValue(false)

    await submit(mountView(), { mode: 'login' })

    expect(auth.askForConfirmationCode).not.toHaveBeenCalled()
    expect(push).not.toHaveBeenCalled()
  })
})
