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
  finishTest: vi.fn(),
  searchSkus: vi.fn(),
  setTestStatus: vi.fn(),
  updateTestSettings: vi.fn(),
  uploadVariant: vi.fn(),
}))
// The detail view asks for the workspace's currency; the unit tier has no network.
vi.mock('@/modules/finreports', () => ({
  useCurrencyStore: () => ({ currency: 'KGS', ensureLoaded: vi.fn() }),
}))

import {
  createTest,
  fetchTest,
  fetchTests,
  fetchVariantImage,
  searchSkus,
} from '@/modules/abTests/api'

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
    vendor_code: 'KID_DRESS_FLORAL',
    name: 'Main photo test',
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
  searchSkus.mockResolvedValue([
    { nm_id: 995716075, vendor_code: 'KID_DRESS_FLORAL', title: 'Dress' },
  ])
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
    await wrapper.get('[data-testid="test-name"]').setValue('Test')
    // The list only opens on focus, the way it does for a user.
    await wrapper.get('[data-testid="sku-search"]').trigger('focus')
    await flushPromises()
    await wrapper.get('[data-testid="sku-option"]').trigger('click')
    await wrapper.get('[data-testid="trigger-mode"]').setValue('time')
    await wrapper.get('[data-testid="slot-minutes"]').setValue('30')

    await wrapper.get('[data-testid="create-test"]').trigger('click')
    await flushPromises()

    const sent = createTest.mock.calls[0][0]
    // The SKU travels as the picked card's nm_id, and no vendor code is sent
    // at all — the backend reads that off the card it resolved.
    expect(sent.nm_id).toBe(995716075)
    expect(sent).not.toHaveProperty('vendor_code')
    expect(sent.trigger_mode).toBe('time')
    expect(sent.slot_minutes).toBe(30)
    expect(sent).not.toHaveProperty('impression_budget')
  })
})

describe('the creation form can bound a turn from both sides', () => {
  it('shows both fields in "Impressions or time"', async () => {
    const wrapper = mountView(AbTestsView)
    await wrapper.get('[data-testid="new-test"]').trigger('click')

    await wrapper.get('[data-testid="trigger-mode"]').setValue('either')

    expect(wrapper.find('[data-testid="impression-budget"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="slot-minutes"]').exists()).toBe(true)
  })

  it('posts both settings, because the rotation reads both', async () => {
    createTest.mockResolvedValue(detail())
    const wrapper = mountView(AbTestsView)
    await wrapper.get('[data-testid="new-test"]').trigger('click')
    await wrapper.get('[data-testid="test-name"]').setValue('Test')
    await wrapper.get('[data-testid="sku-search"]').trigger('focus')
    await flushPromises()
    await wrapper.get('[data-testid="sku-option"]').trigger('click')
    await wrapper.get('[data-testid="trigger-mode"]').setValue('either')
    await wrapper.get('[data-testid="impression-budget"]').setValue('1000')
    await wrapper.get('[data-testid="slot-minutes"]').setValue('20')

    await wrapper.get('[data-testid="create-test"]').trigger('click')
    await flushPromises()

    const sent = createTest.mock.calls[0][0]
    expect(sent.trigger_mode).toBe('either')
    expect(sent.impression_budget).toBe(1000)
    expect(sent.slot_minutes).toBe(20)
  })
})

describe('the detail page reports the trigger in force', () => {
  it('reads the slot length in time mode', async () => {
    fetchTest.mockResolvedValue(detail({ trigger_mode: 'time', slot_minutes: 30 }))
    const wrapper = mountView(AbTestDetailView)
    await flushPromises()

    // Scoped to the header: the page's empty-state help text also mentions
    // impressions, and asserting over the whole page would pass or
    // fail on wording that has nothing to do with the trigger.
    const header = wrapper.get('header').text()
    expect(header).toContain('Photo changes every 30 min')
    expect(header).not.toContain('impressions')
  })

  it('reads the budget in impressions mode', async () => {
    fetchTest.mockResolvedValue(detail({ trigger_mode: 'impressions', impression_budget: 2000 }))
    const wrapper = mountView(AbTestDetailView)
    await flushPromises()

    const header = wrapper.get('header').text()
    expect(header).toContain('Photo changes every 2,000 impressions')
    expect(header).not.toContain('min')
  })

  it('names both bounds, joined by "or", in "Impressions or time"', async () => {
    // "or", never "and": the turn ends at the FIRST of them, and "and" would
    // read as a photo waiting for both.
    fetchTest.mockResolvedValue(
      detail({ trigger_mode: 'either', impression_budget: 1000, slot_minutes: 20 }),
    )
    const wrapper = mountView(AbTestDetailView)
    await flushPromises()

    const header = wrapper.get('header').text()
    expect(header).toContain('1,000 impressions or 20 min')
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

describe('the SKU is picked, not typed', () => {
  it('cannot submit until a card is chosen', async () => {
    // A free-text field let a test be created against WB ID `1` — a card
    // no workspace owns, which the poller finds no advertising for and a
    // rotation would try to upload a photo to.
    const wrapper = mountView(AbTestsView)
    await wrapper.get('[data-testid="new-test"]').trigger('click')
    await wrapper.get('[data-testid="test-name"]').setValue('Test')

    expect(wrapper.get('[data-testid="create-test"]').attributes('disabled')).toBeDefined()

    await wrapper.get('[data-testid="sku-search"]').trigger('focus')
    await flushPromises()
    await wrapper.get('[data-testid="sku-option"]').trigger('click')

    expect(wrapper.get('[data-testid="create-test"]').attributes('disabled')).toBeUndefined()
  })

  it('has no separate vendor-code field to disagree with the card', async () => {
    // Both identifiers reach the same card and the vendor code is read off
    // it; a second field could drift and make the test unfindable by the
    // SKU it actually runs on.
    const wrapper = mountView(AbTestsView)
    await wrapper.get('[data-testid="new-test"]').trigger('click')

    expect(wrapper.find('[data-testid="test-nm-id"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Vendor code')
  })

  it('searches the catalog as the user types', async () => {
    const wrapper = mountView(AbTestsView)
    await wrapper.get('[data-testid="new-test"]').trigger('click')
    await wrapper.get('[data-testid="sku-search"]').setValue('FLORAL')
    await flushPromises()

    expect(searchSkus).toHaveBeenCalledWith('FLORAL', expect.anything())
  })

  it('says so when the catalog has no such SKU', async () => {
    // The alternative is an empty dropdown, which reads as "still loading".
    searchSkus.mockResolvedValue([])
    const wrapper = mountView(AbTestsView)
    await wrapper.get('[data-testid="new-test"]').trigger('click')
    await wrapper.get('[data-testid="sku-search"]').trigger('focus')
    await wrapper.get('[data-testid="sku-search"]').setValue('no-such-sku')
    await flushPromises()

    expect(wrapper.get('[data-testid="sku-empty"]').text()).toContain('No such SKU')
  })
})
