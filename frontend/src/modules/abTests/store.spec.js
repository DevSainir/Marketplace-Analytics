import { createPinia, setActivePinia } from 'pinia'

import {
  createTest,
  deleteTest,
  deleteVariant,
  fetchTest,
  fetchTests,
  fetchVariantImage,
  finishTest,
  setTestStatus,
  updateTestSettings,
  uploadVariant,
} from '@/modules/abTests/api'
import { MAX_VARIANTS, useAbTestsStore } from '@/modules/abTests/store'

vi.mock('@/modules/abTests/api', () => ({
  createTest: vi.fn(),
  deleteTest: vi.fn(),
  deleteVariant: vi.fn(),
  fetchTest: vi.fn(),
  fetchTests: vi.fn(),
  fetchVariantImage: vi.fn(),
  finishTest: vi.fn(),
  setTestStatus: vi.fn(),
  updateTestSettings: vi.fn(),
  uploadVariant: vi.fn(),
}))

const TEST_ID = 'aaaaaaaa-0000-7000-8000-000000000001'

function detail(variantCount) {
  return {
    id: TEST_ID,
    nm_id: 995716075,
    name: 'Main photo test',
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

describe('A/B tests photo object URLs', () => {
  // The image route is authenticated and the access token lives in memory, so
  // `<img src="/api/…">` is refused — the bytes come through the API client and
  // reach the tag as object URLs instead. That makes their lifetime the store's
  // problem: an object URL pins its blob until revoked.
  let created
  let revoked

  beforeEach(() => {
    created = 0
    revoked = []
    vi.stubGlobal('URL', {
      createObjectURL: () => `blob:fake/${++created}`,
      revokeObjectURL: (url) => revoked.push(url),
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('exposes one object URL per variant', async () => {
    fetchTest.mockResolvedValue(detail(2))
    fetchVariantImage.mockResolvedValue(new Blob(['jpeg']))
    const store = useAbTestsStore()
    await store.loadTest(TEST_ID)

    await store.loadImages(TEST_ID)

    expect(Object.keys(store.imageUrls)).toEqual(['v0', 'v1'])
    expect(store.imageUrls.v0).toMatch(/^blob:/)
  })

  it('still renders a row whose photo could not be fetched', async () => {
    // The metrics are most of what the table is for; one unreachable image
    // must not blank the whole rotation.
    fetchTest.mockResolvedValue(detail(2))
    fetchVariantImage
      .mockRejectedValueOnce(new Error('boom'))
      .mockResolvedValueOnce(new Blob(['jpeg']))
      // The retry, which fails too — see the test below for why there is one.
      .mockRejectedValueOnce(new Error('boom'))
    const store = useAbTestsStore()
    await store.loadTest(TEST_ID)

    await store.loadImages(TEST_ID)

    expect(store.imageUrls.v0).toBeUndefined()
    expect(store.imageUrls.v1).toMatch(/^blob:/)
  })

  it('does not retry a photo the server says is not there', async () => {
    // A 404 is an answer, not a hiccup. Retrying it doubles the requests of a
    // rotation whose images are genuinely gone and changes nothing.
    fetchTest.mockResolvedValue(detail(1))
    fetchVariantImage.mockRejectedValue(
      Object.assign(new Error('404'), { response: { status: 404 } }),
    )
    const store = useAbTestsStore()
    await store.loadTest(TEST_ID)
    fetchVariantImage.mockClear()

    await store.loadImages(TEST_ID)

    expect(fetchVariantImage).toHaveBeenCalledTimes(1)
    expect(store.imageUrls.v0).toBeUndefined()
  })

  it('gives a photo the object storage dropped a second chance', async () => {
    // The bucket behind these returns an intermittent 502: the same eleven
    // objects failed on all of them once and succeeded on all of them a minute
    // later. Without a retry that photo is missing until the page is reloaded,
    // which is what "the seventh picture never loaded" was.
    fetchTest.mockResolvedValue(detail(1))
    fetchVariantImage
      .mockRejectedValueOnce(new Error('502'))
      .mockResolvedValueOnce(new Blob(['jpeg']))
    const store = useAbTestsStore()
    await store.loadTest(TEST_ID)

    await store.loadImages(TEST_ID)

    expect(store.imageUrls.v0).toMatch(/^blob:/)
  })

  it('revokes the previous URLs when the photos are reloaded', async () => {
    // An upload replaces the whole detail, so this runs on every added photo.
    // Without the revoke a ten-photo rotation leaks ten blobs per upload.
    fetchTest.mockResolvedValue(detail(1))
    fetchVariantImage.mockResolvedValue(new Blob(['jpeg']))
    const store = useAbTestsStore()
    await store.loadTest(TEST_ID)
    await store.loadImages(TEST_ID)
    const first = store.imageUrls.v0

    await store.loadImages(TEST_ID)

    expect(revoked).toContain(first)
    expect(store.imageUrls.v0).not.toBe(first)
  })

  it('lets the newest load win when a slower older one finishes after it', async () => {
    // Selecting three files uploads them one at a time, and each upload
    // replaces the whole detail — so several loads are in flight at once. The
    // run that fetched a single photo used to finish last and overwrite the run
    // that fetched three, leaving two rows with no thumbnail at all.
    let arriveLate
    const slow = new Promise((resolve) => {
      arriveLate = () => resolve(new Blob(['jpeg']))
    })
    fetchTest.mockResolvedValue(detail(1))
    fetchVariantImage.mockReturnValueOnce(slow).mockResolvedValue(new Blob(['jpeg']))
    const store = useAbTestsStore()
    await store.loadTest(TEST_ID)
    const stale = store.loadImages(TEST_ID)
    store.detail = detail(3)
    const fresh = store.loadImages(TEST_ID)
    await fresh

    arriveLate()
    await stale

    expect(Object.keys(store.imageUrls)).toEqual(['v0', 'v1', 'v2'])
  })

  it('releases every URL when the view goes away', async () => {
    fetchTest.mockResolvedValue(detail(2))
    fetchVariantImage.mockResolvedValue(new Blob(['jpeg']))
    const store = useAbTestsStore()
    await store.loadTest(TEST_ID)
    await store.loadImages(TEST_ID)

    store.releaseImages()

    expect(revoked).toHaveLength(2)
    expect(store.imageUrls).toEqual({})
  })
})

describe('A/B tests store', () => {
  it('sends the search needle to the backend rather than filtering locally', async () => {
    // The backend matches name, WB ID, vendor code and status in one predicate;
    // a client-side filter would quietly disagree with it.
    fetchTests.mockResolvedValue([])
    const store = useAbTestsStore()

    await store.search('  FLORAL  ')

    expect(fetchTests).toHaveBeenCalledWith({ q: 'FLORAL' }, expect.anything())
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
    uploadVariant.mockRejectedValue({ response: { data: { detail: 'The file is empty.' } } })
    const store = useAbTestsStore()
    await store.loadTest(TEST_ID)

    const ok = await store.addPhoto(TEST_ID, new File([''], 'photo.jpg'))

    expect(ok).toBe(false)
    expect(store.error).toBe('The file is empty.')
    expect(store.detail.variants).toHaveLength(2)
  })

  it('clears a previous upload error once one succeeds', async () => {
    // Otherwise a stale banner outlives the problem it described, and the user
    // is told the upload failed while looking at the photo it produced.
    fetchTest.mockResolvedValue(detail(0))
    uploadVariant.mockRejectedValueOnce({ response: { data: { detail: 'The file is empty.' } } })
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
    uploadVariant.mockRejectedValue({ response: { data: { detail: 'The file is empty.' } } })
    const store = useAbTestsStore()
    await store.loadTest(TEST_ID)

    await store.addPhoto(TEST_ID, new File([''], 'photo.jpg'))

    expect(store.saving).toBe(false)
  })

  it('surfaces a rejected start instead of showing the test as running', async () => {
    // Starting installs the first photo on the seller's live card. A rejection
    // means the card was NOT touched, so the row must stay as it was.
    fetchTests.mockResolvedValue([{ id: TEST_ID, status: 'draft' }])
    setTestStatus.mockRejectedValue({ response: { data: { detail: 'Upload a photo' } } })
    const store = useAbTestsStore()
    await store.loadTests()

    const ok = await store.changeStatus(TEST_ID, 'running')

    expect(ok).toBe(false)
    expect(store.error).toBeTruthy()
    expect(store.rows[0].status).toBe('draft')
  })

  it('shows a finished test as finished, in the list and on the page', async () => {
    fetchTests.mockResolvedValue([{ id: TEST_ID, status: 'paused' }])
    finishTest.mockResolvedValue({ ...detail(2), status: 'cancelled', active_variant_id: 'v1' })
    const store = useAbTestsStore()
    await store.loadTests()

    const ok = await store.finish(TEST_ID, 'v1')

    expect(ok).toBe(true)
    expect(finishTest).toHaveBeenCalledWith(TEST_ID, 'v1')
    expect(store.detail.status).toBe('cancelled')
    expect(store.rows[0].status).toBe('cancelled')
  })

  it('surfaces a refused finish and leaves the test as it was', async () => {
    // The chosen photo goes up before the test is closed, so a refusal means
    // neither happened.
    fetchTests.mockResolvedValue([{ id: TEST_ID, status: 'paused' }])
    finishTest.mockRejectedValue({ response: { data: { detail: 'WB rejected the photo.' } } })
    const store = useAbTestsStore()
    await store.loadTests()

    const ok = await store.finish(TEST_ID, 'v1')

    expect(ok).toBe(false)
    expect(store.error).toBeTruthy()
    expect(store.rows[0].status).toBe('paused')
    expect(store.saving).toBe(false)
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

  it('sends only the setting the chosen trigger actually uses', async () => {
    // The backend REFUSES a body carrying the other mode's setting rather than
    // ignoring it, so a form that always sent both fields would 422 on every
    // submit. The exclusivity is a product rule — a test rotating on
    // "impressions or time, whichever first" would measure its photos over
    // different exposures — and the client has to respect it.
    createTest.mockResolvedValue({ id: TEST_ID })
    const store = useAbTestsStore()

    await store.create({ nm_id: 1, name: 'Test', trigger_mode: 'time', slot_minutes: 30 })

    const sent = createTest.mock.calls[0][0]
    expect(sent.slot_minutes).toBe(30)
    expect(sent).not.toHaveProperty('impression_budget')
  })

  it('refreshes the open test after its trigger changes', async () => {
    // The trigger is shown in the page header, so a stale copy would tell the
    // user the rotation is still counting impressions after they moved it onto
    // a clock — and the next poll would disagree with the screen.
    fetchTests.mockResolvedValue([{ id: TEST_ID, trigger_mode: 'impressions' }])
    fetchTest.mockResolvedValue({ ...detail(1), trigger_mode: 'time', slot_minutes: 30 })
    updateTestSettings.mockResolvedValue({ id: TEST_ID, trigger_mode: 'time' })
    const store = useAbTestsStore()
    await store.loadTests()
    await store.loadTest(TEST_ID)

    const ok = await store.updateSettings(TEST_ID, { trigger_mode: 'time', slot_minutes: 30 })

    expect(ok).toBe(true)
    expect(store.rows[0].trigger_mode).toBe('time')
    expect(store.detail.slot_minutes).toBe(30)
  })

  it('surfaces a refused trigger change and leaves the test as it was', async () => {
    // The backend refuses a body carrying the other mode's setting. Showing
    // nothing would leave the user believing the change landed.
    fetchTests.mockResolvedValue([{ id: TEST_ID, trigger_mode: 'impressions' }])
    updateTestSettings.mockRejectedValue({
      response: { data: { detail: 'A test rotating by impressions takes no time per variant.' } },
    })
    const store = useAbTestsStore()
    await store.loadTests()

    const ok = await store.updateSettings(TEST_ID, { slot_minutes: 30 })

    expect(ok).toBe(false)
    expect(store.error).toContain('by impressions')
    expect(store.rows[0].trigger_mode).toBe('impressions')
  })

  it('prepends a created test so it is visible without a reload', async () => {
    fetchTests.mockResolvedValue([{ id: 'older' }])
    createTest.mockResolvedValue({ id: TEST_ID })
    const store = useAbTestsStore()
    await store.loadTests()

    await store.create({ nm_id: 995716075, name: 'New' })

    expect(store.rows.map((row) => row.id)).toEqual([TEST_ID, 'older'])
  })
})
