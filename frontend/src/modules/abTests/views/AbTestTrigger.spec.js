import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import AbTestDetailView from '@/modules/abTests/views/AbTestDetailView.vue'
import AbTestsView from '@/modules/abTests/views/AbTestsView.vue'

vi.mock('@/modules/abTests/api', () => ({
  createTest: vi.fn(),
  deleteTest: vi.fn(),
  deleteVariant: vi.fn(),
  fetchTest: vi.fn(),
  fetchTests: vi.fn(),
  fetchVariantImage: vi.fn(),
  setTestStatus: vi.fn(),
  updateTestSettings: vi.fn(),
  uploadVariant: vi.fn(),
}))

import { createTest, fetchTest, fetchTests, fetchVariantImage } from '@/modules/abTests/api'

const TEST_ID = 'aaaaaaaa-0000-7000-8000-000000000001'

const push = vi.fn()
vi.mock('vue-router', async () => {
  const actual = await vi.importActual('vue-router')
  return {
    ...actual,
    useRouter: () => ({ push }),
    useRoute: () => ({ params: { testId: TEST_ID } }),
  }
})

function detail(overrides = {}) {
  return {
    id: TEST_ID,
    nm_id: 995716075,
    vendor_code: 'ДЕТ_ПЛАТЬЕ_ЦВЕТОЧЕК',
    name: 'Тест главного фото',
    status: 'running',
    trigger_mode: 'impressions',
    impression_budget: 10000,
    slot_minutes: 60,
    active_variant_id: null,
    variant_count: 0,
    variants: [],
    started_at: null,
    finished_at: null,
    created_at: '2026-09-04T10:00:00Z',
    ...overrides,
  }
}

function mountView(component) {
  const pinia = createPinia()
  setActivePinia(pinia)
  return mount(component, {
    global: {
      plugins: [pinia],
      stubs: { RouterLink: { template: '<a><slot /></a>' } },
    },
  })
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  fetchTests.mockResolvedValue([])
  fetchVariantImage.mockResolvedValue(new Blob(['jpeg']))
})

// These two assertions used to live only in the browser tier, where they were
// never reached: the journey failed earlier, on a creation that answered 500,
// so the trigger switch and its label shipped unexercised. They are properties
// of the components, so they belong here — the browser tier keeps them too, but
// as part of a journey rather than as their only coverage.
describe('the creation form sends one trigger, never both', () => {
  it('shows the field the chosen mode uses and hides the other', async () => {
    const wrapper = mountView(AbTestsView)
    await wrapper.get('[data-testid="new-test"]').trigger('click')

    expect(wrapper.find('[data-testid="impression-budget"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="slot-minutes"]').exists()).toBe(false)

    await wrapper.get('[data-testid="trigger-mode"]').setValue('time')

    expect(wrapper.find('[data-testid="slot-minutes"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="impression-budget"]').exists()).toBe(false)
  })

  it('posts only the setting belonging to the chosen mode', async () => {
    // The API refuses a body carrying the other mode's field rather than
    // ignoring it, so sending both would 422 on every submit.
    createTest.mockResolvedValue(detail())
    const wrapper = mountView(AbTestsView)
    await wrapper.get('[data-testid="new-test"]').trigger('click')
    await wrapper.get('[data-testid="test-name"]').setValue('Тест')
    await wrapper.get('[data-testid="test-nm-id"]').setValue('995716075')
    await wrapper.get('[data-testid="trigger-mode"]').setValue('time')
    await wrapper.get('[data-testid="slot-minutes"]').setValue('30')

    await wrapper.get('[data-testid="create-test"]').trigger('click')
    await flushPromises()

    const sent = createTest.mock.calls[0][0]
    expect(sent.trigger_mode).toBe('time')
    expect(sent.slot_minutes).toBe(30)
    expect(sent).not.toHaveProperty('impression_budget')
  })
})

describe('the detail page reports the trigger in force', () => {
  it('reads the slot length in time mode', async () => {
    fetchTest.mockResolvedValue(detail({ trigger_mode: 'time', slot_minutes: 30 }))
    const wrapper = mountView(AbTestDetailView)
    await flushPromises()

    // Scoped to the header: the page's empty-state help text also mentions
    // показы, and asserting over the whole page would pass or fail on wording
    // that has nothing to do with the trigger.
    const header = wrapper.get('header').text()
    expect(header).toContain('Смена фото каждые 30 мин')
    expect(header).not.toContain('показов')
  })

  it('reads the budget in impressions mode', async () => {
    fetchTest.mockResolvedValue(detail({ trigger_mode: 'impressions', impression_budget: 2000 }))
    const wrapper = mountView(AbTestDetailView)
    await flushPromises()

    const header = wrapper.get('header').text()
    expect(header).toContain('Смена фото каждые')
    expect(header).toContain('показов')
    expect(header).not.toContain('мин')
  })

  it('offers the editor while the test can still rotate', async () => {
    fetchTest.mockResolvedValue(detail({ status: 'running' }))
    const wrapper = mountView(AbTestDetailView)
    await flushPromises()

    expect(wrapper.find('[data-testid="edit-trigger"]').exists()).toBe(true)
  })

  it('hides the editor once the test has finished', async () => {
    // A finished test's settings are the record of how its results were made;
    // the API refuses to change them, so the affordance must not be offered.
    fetchTest.mockResolvedValue(detail({ status: 'completed' }))
    const wrapper = mountView(AbTestDetailView)
    await flushPromises()

    expect(wrapper.find('[data-testid="edit-trigger"]').exists()).toBe(false)
  })
})
