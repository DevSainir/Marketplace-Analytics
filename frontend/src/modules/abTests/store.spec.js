import { createPinia, setActivePinia } from 'pinia'

import {
  createTest,
  deleteTest,
  deleteVariant,
  fetchTest,
  fetchTests,
  setTestStatus,
  uploadVariant,
} from '@/modules/abTests/api'
import { MAX_VARIANTS, useAbTestsStore } from '@/modules/abTests/store'

vi.mock('@/modules/abTests/api', () => ({
  createTest: vi.fn(),
  deleteTest: vi.fn(),
  deleteVariant: vi.fn(),
  fetchTest: vi.fn(),
  fetchTests: vi.fn(),
  setTestStatus: vi.fn(),
  uploadVariant: vi.fn(),
}))

const TEST_ID = 'aaaaaaaa-0000-7000-8000-000000000001'

function detail(variantCount) {
  return {
    id: TEST_ID,
    nm_id: 995716075,
    name: 'Тест главного фото',
    status: 'draft',
    variants: Array.from({ length: variantCount }, (_, index) => ({
      variant_id: `v${index}`,
      position: index + 1,
    })),
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
})

describe('A/Б-tests store', () => {
  it('sends the search needle to the backend rather than filtering locally', async () => {
    // The backend matches name, both articles and status in one predicate;
    // a client-side filter would quietly disagree with it.
    fetchTests.mockResolvedValue([])
    const store = useAbTestsStore()

    await store.search('  ЦВЕТОЧЕК  ')

    expect(fetchTests).toHaveBeenCalledWith({ q: 'ЦВЕТОЧЕК' }, expect.anything())
  })

  it('omits the parameter entirely when the box is empty', async () => {
    fetchTests.mockResolvedValue([])
    const store = useAbTestsStore()

    await store.search('   ')

    expect(fetchTests).toHaveBeenCalledWith({}, expect.anything())
  })

  it('does not report a cancelled request as an error', async () => {
    // Every keystroke aborts the previous fetch; showing that as a failure
    // would flash an error banner while the user is still typing.
    fetchTests.mockRejectedValue({ code: 'ERR_CANCELED' })
    const store = useAbTestsStore()

    await store.loadTests()

    expect(store.error).toBe('')
  })

  it('closes uploads once the rotation is full', async () => {
    fetchTest.mockResolvedValue(detail(MAX_VARIANTS))
    const store = useAbTestsStore()

    await store.loadTest(TEST_ID)

    expect(store.canUpload).toBe(false)
    expect(store.remainingSlots).toBe(0)
  })

  it('reports how many photo slots are left', async () => {
    fetchTest.mockResolvedValue(detail(3))
    const store = useAbTestsStore()

    await store.loadTest(TEST_ID)

    expect(store.remainingSlots).toBe(MAX_VARIANTS - 3)
  })

  it('replaces the detail with the refreshed test the upload returns', async () => {
    // The upload endpoint answers with the whole test so the photo list and the
    // result table cannot disagree; the store must not keep the stale copy.
    fetchTest.mockResolvedValue(detail(1))
    uploadVariant.mockResolvedValue(detail(2))
    const store = useAbTestsStore()
    await store.loadTest(TEST_ID)

    const ok = await store.addPhoto(TEST_ID, new File([''], 'photo.jpg'))

    expect(ok).toBe(true)
    expect(store.detail.variants).toHaveLength(2)
  })

  it('surfaces a rejected upload instead of leaving the table silently empty', async () => {
    // A refused upload has to SAY so. The failure mode this guards against is
    // the one that shipped on 2026-08-20: every upload answered 422, and
    // because the table only renders `variants`, the page showed an empty
    // result table and no reason for it. An empty table reads as "no photos
    // yet", which is exactly the wrong thing for a user to conclude.
    fetchTest.mockResolvedValue(detail(0))
    uploadVariant.mockRejectedValue({
      response: { data: { detail: [{ msg: 'Field required' }] } },
    })
    const store = useAbTestsStore()
    await store.loadTest(TEST_ID)

    const ok = await store.addPhoto(TEST_ID, new File([''], 'photo.jpg'))

    expect(ok).toBe(false)
    expect(store.error).toBe('Field required')
    expect(store.detail.variants).toHaveLength(0)
  })

  it('keeps the photos already uploaded when a later one is refused', async () => {
    // The view uploads a multi-file selection one at a time, so a rejection
    // part-way through must not discard the ones that already landed — the
    // rotation the user can still start is whatever did get through.
    fetchTest.mockResolvedValue(detail(2))
    uploadVariant.mockRejectedValue({ response: { data: { detail: 'Файл пустой.' } } })
    const store = useAbTestsStore()
    await store.loadTest(TEST_ID)

    const ok = await store.addPhoto(TEST_ID, new File([''], 'photo.jpg'))

    expect(ok).toBe(false)
    expect(store.error).toBe('Файл пустой.')
    expect(store.detail.variants).toHaveLength(2)
  })

  it('clears a previous upload error once one succeeds', async () => {
    // Otherwise a stale banner outlives the problem it described, and the user
    // is told the upload failed while looking at the photo it produced.
    fetchTest.mockResolvedValue(detail(0))
    uploadVariant.mockRejectedValueOnce({ response: { data: { detail: 'Файл пустой.' } } })
    const store = useAbTestsStore()
    await store.loadTest(TEST_ID)
    await store.addPhoto(TEST_ID, new File([''], 'bad.jpg'))

    uploadVariant.mockResolvedValue(detail(1))
    const ok = await store.addPhoto(TEST_ID, new File([''], 'good.jpg'))

    expect(ok).toBe(true)
    expect(store.error).toBe('')
    expect(store.detail.variants).toHaveLength(1)
  })

  it('stops saving even when the upload throws', async () => {
    // `saving` disables the file input and the start button. Leaving it stuck
    // on after a failure locks the user out of retrying the very upload the
    // error message is telling them to fix.
    fetchTest.mockResolvedValue(detail(0))
    uploadVariant.mockRejectedValue({ response: { data: { detail: 'Файл пустой.' } } })
    const store = useAbTestsStore()
    await store.loadTest(TEST_ID)

    await store.addPhoto(TEST_ID, new File([''], 'photo.jpg'))

    expect(store.saving).toBe(false)
  })

  it('surfaces a rejected start instead of showing the test as running', async () => {
    // Starting installs the first photo on the seller's live card. A rejection
    // means the card was NOT touched, so the row must stay as it was.
    fetchTests.mockResolvedValue([{ id: TEST_ID, status: 'draft' }])
    setTestStatus.mockRejectedValue({ response: { data: { detail: 'Загрузите фото' } } })
    const store = useAbTestsStore()
    await store.loadTests()

    const ok = await store.changeStatus(TEST_ID, 'running')

    expect(ok).toBe(false)
    expect(store.error).toBeTruthy()
    expect(store.rows[0].status).toBe('draft')
  })

  it('drops a deleted test from the list without refetching', async () => {
    fetchTests.mockResolvedValue([{ id: TEST_ID }, { id: 'other' }])
    deleteTest.mockResolvedValue(undefined)
    const store = useAbTestsStore()
    await store.loadTests()

    await store.remove(TEST_ID)

    expect(store.rows.map((row) => row.id)).toEqual(['other'])
  })

  it('reloads the test after a photo is removed', async () => {
    // Deleting returns 204 with no body, so the table would keep the removed
    // row unless the detail is fetched again.
    fetchTest.mockResolvedValueOnce(detail(2)).mockResolvedValueOnce(detail(1))
    deleteVariant.mockResolvedValue(undefined)
    const store = useAbTestsStore()
    await store.loadTest(TEST_ID)

    await store.removePhoto(TEST_ID, 'v0')

    expect(store.detail.variants).toHaveLength(1)
  })

  it('prepends a created test so it is visible without a reload', async () => {
    fetchTests.mockResolvedValue([{ id: 'older' }])
    createTest.mockResolvedValue({ id: TEST_ID })
    const store = useAbTestsStore()
    await store.loadTests()

    await store.create({ nm_id: 995716075, name: 'Новый' })

    expect(store.rows.map((row) => row.id)).toEqual([TEST_ID, 'older'])
  })
})
