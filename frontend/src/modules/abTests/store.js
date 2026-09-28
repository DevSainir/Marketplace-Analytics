/**
 * A/Б-tests Pinia store (Composition-API setup style).
 *
 * Owns the module's fetching so the two views stay declarative. It exists
 * rather than each view fetching for itself because the pages are coupled in
 * one direction: uploading a photo or starting a test changes the row the list
 * shows, so those writes invalidate the list instead of leaving a stale
 * «Черновик» chip behind a route change.
 *
 * The search needle is held here too. The backend matches it against the test
 * name, both articles and the status — one box for the whole row — so the view
 * has nothing to filter client-side.
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { extractErrorMessage } from '@/core/api/axios'
import {
  createTest,
  deleteTest,
  deleteVariant,
  fetchTest,
  fetchTests,
  fetchVariantImage,
  finishTest,
  searchSkus,
  setTestStatus,
  setVariantExcluded,
  updateTestSettings,
  uploadVariant,
} from '@/modules/abTests/api'

/** Statuses as the backend spells them, with their Russian labels. */
export const STATUS_LABELS = {
  draft: 'Черновик',
  running: 'Запущен',
  paused: 'На паузе',
  completed: 'Завершён',
  cancelled: 'Завершён',
}

/**
 * A test's status in words — with the reason, for a pause the seller did not make.
 *
 * @param {{status: string, paused_by_ads?: boolean}} test A list row or the detail.
 * @returns {string} «На паузе · нет рекламы» for the rotation's own pause, the
 *   plain label otherwise.
 */
export function statusLabel(test) {
  if (test.status === 'paused' && test.paused_by_ads) return 'На паузе · нет рекламы'
  return STATUS_LABELS[test.status] || test.status
}

/** Product cap on photos in one rotation; mirrors the backend's own limit. */
export const MAX_VARIANTS = 10

/** Photos fetched at once. Six is where browsers queue per origin anyway. */
const IMAGE_FETCH_LANES = 6

/** Pause before the second attempt at one photo — see `loadImages`. */
const IMAGE_RETRY_MS = 400

/**
 * Fetch one variant image, giving the object storage a second chance.
 *
 * The failure this exists for is a 502 from the bucket that clears by itself;
 * without the retry the photo is missing until the page is reloaded.
 *
 * @param {string} testId Test identifier.
 * @param {string} variantId Variant identifier.
 * @returns {Promise<Blob|null>} The image, or null if both attempts failed.
 */
async function fetchImageTwice(testId, variantId) {
  try {
    return await fetchVariantImage(testId, variantId)
  } catch (err) {
    // A 4xx is an answer: «этого файла нет» does not become «есть» half a
    // second later, and a rotation whose images are genuinely gone would
    // otherwise spend twenty requests proving it.
    const status = err.response?.status ?? 0
    if (status >= 400 && status < 500) return null
    await new Promise((resolve) => setTimeout(resolve, IMAGE_RETRY_MS))
  }
  try {
    return await fetchVariantImage(testId, variantId)
  } catch {
    return null
  }
}

export const useAbTestsStore = defineStore('abTests', () => {
  const tests = ref([])
  const detail = ref(null)
  // variant_id -> object URL. The images are authenticated, so they are
  // fetched as blobs and handed to `<img>` as object URLs; the browser would
  // send neither the access token nor the workspace header on its own.
  const imageUrls = ref({})
  const query = ref('')
  const skuOptions = ref([])
  const loading = ref(false)
  const saving = ref(false)
  const error = ref('')

  let listController = null
  let skuController = null
  // Generation counter for `loadImages` — see it for why the runs overlap.
  let imagesRun = 0

  /** Tests as the list renders them (the backend already ordered them). */
  const rows = computed(() => tests.value)

  /**
   * How many photos the open test holds.
   *
   * «Главное» counts. It is an upload like the rest — it used to be captured
   * off WB's CDN, and leaving it out of this count was how the seller avoided
   * paying a slot for a photo they never chose.
   */
  const uploadedCount = computed(() => (detail.value?.variants ?? []).length)

  /** Whether the open test already carries a «Главное» photo — at most one. */
  const hasMainPhoto = computed(() =>
    (detail.value?.variants ?? []).some((variant) => variant.is_original),
  )

  /** True while the open test still has room for another photo. */
  const canUpload = computed(() => !!detail.value && uploadedCount.value < MAX_VARIANTS)

  /** How many more photos the open test accepts. */
  const remainingSlots = computed(() =>
    detail.value ? Math.max(0, MAX_VARIANTS - uploadedCount.value) : 0,
  )

  /**
   * Load the list, cancelling any request the user has already typed past.
   *
   * @returns {Promise<void>}
   */
  async function loadTests() {
    listController?.abort()
    listController = new AbortController()
    loading.value = true
    error.value = ''
    try {
      tests.value = await fetchTests(
        query.value.trim() ? { q: query.value.trim() } : {},
        listController.signal,
      )
    } catch (err) {
      // An aborted request is the user typing, not a failure.
      if (err.code !== 'ERR_CANCELED') error.value = extractErrorMessage(err)
    } finally {
      loading.value = false
    }
  }

  /**
   * Load catalogue options for the article picker.
   *
   * A test may only name an article its workspace owns — the API refuses the
   * rest — so the field is a picker rather than free text. Cancels the previous
   * request, because this runs on every keystroke.
   *
   * @param {string} needle Fragment of either article, or of the title.
   * @returns {Promise<void>}
   */
  async function loadSkuOptions(needle) {
    skuController?.abort()
    skuController = new AbortController()
    try {
      skuOptions.value = await searchSkus(needle, skuController.signal)
    } catch (err) {
      if (err.code !== 'ERR_CANCELED') skuOptions.value = []
    }
  }

  /**
   * Set the search needle and reload.
   *
   * @param {string} value Raw input value.
   * @returns {Promise<void>}
   */
  async function search(value) {
    query.value = value
    await loadTests()
  }

  /**
   * Load one test and its result table.
   *
   * @param {string} testId Test identifier.
   * @returns {Promise<void>}
   */
  async function loadTest(testId) {
    loading.value = true
    error.value = ''
    try {
      detail.value = await fetchTest(testId)
    } catch (err) {
      error.value = extractErrorMessage(err)
      detail.value = null
    } finally {
      loading.value = false
    }
  }

  /**
   * Re-read the open test without disturbing the page.
   *
   * Deliberately not `loadTest`: this runs on a timer while a rotation is
   * live, and flipping `loading` every minute would blank the results under
   * the reader's cursor. A failure is swallowed for the same reason — a
   * background poll that paints an error banner over a working page is worse
   * than a figure that is one minute stale.
   *
   * @param {string} testId Test identifier.
   * @returns {Promise<void>}
   */
  async function refreshDetail(testId) {
    try {
      const fresh = await fetchTest(testId)
      if (detail.value?.id === fresh.id) detail.value = fresh
    } catch {
      // Keep what is on screen.
    }
  }

  /**
   * Run one write with the page's shared `saving` flag and error line.
   *
   * @param {() => Promise<void>} run The write.
   * @returns {Promise<boolean>} Whether it succeeded; the error is on `error`.
   */
  async function write(run) {
    saving.value = true
    error.value = ''
    try {
      await run()
      return true
    } catch (err) {
      error.value = extractErrorMessage(err)
      return false
    } finally {
      saving.value = false
    }
  }

  /**
   * Create a draft test and prepend it to the list.
   *
   * @param {{nm_id: number, name: string, vendor_code?: string,
   *          impression_budget?: number}} payload
   * @returns {Promise<object|null>} The created test, or null on failure.
   */
  async function create(payload) {
    saving.value = true
    error.value = ''
    try {
      const created = await createTest(payload)
      tests.value = [created, ...tests.value]
      return created
    } catch (err) {
      error.value = extractErrorMessage(err)
      return null
    } finally {
      saving.value = false
    }
  }

  /**
   * Upload one photo into the open test.
   *
   * @param {string} testId Test identifier.
   * @param {File} file The picture.
   * @param {{main?: boolean}} [options] `main: true` files it as «Главное».
   * @returns {Promise<boolean>} Whether it was accepted.
   */
  async function addPhoto(testId, file, { main = false } = {}) {
    return write(async () => {
      detail.value = await uploadVariant(testId, file, { main })
    })
  }

  /**
   * Remove a photo from the open test.
   *
   * @param {string} testId Test identifier.
   * @param {string} variantId Variant identifier.
   * @returns {Promise<boolean>} Whether it was removed.
   */
  async function removePhoto(testId, variantId) {
    return write(async () => {
      await deleteVariant(testId, variantId)
      detail.value = await fetchTest(testId)
    })
  }

  /**
   * Take a photo out of the rotation, or put it back.
   *
   * Allowed while the test is running — that is the whole point of it. Nothing
   * is deleted, so the result table goes on showing what the photo earned; it
   * just stops being dealt.
   *
   * @param {string} testId Test identifier.
   * @param {string} variantId Variant identifier.
   * @param {boolean} excluded True to take it out.
   * @returns {Promise<boolean>} True when the change stuck.
   */
  async function toggleExclusion(testId, variantId, excluded) {
    return write(async () => {
      detail.value = await setVariantExcluded(testId, variantId, excluded)
    })
  }

  /**
   * Start or pause a test. Finishing goes through `finish`, which carries the
   * photo the card keeps.
   *
   * Starting installs the first photo on the seller's card, so a failure here
   * is shown rather than swallowed: the card was not touched.
   *
   * @param {string} testId Test identifier.
   * @param {'running'|'paused'} status Target status.
   * @returns {Promise<boolean>} Whether the transition happened.
   */
  async function changeStatus(testId, status) {
    return write(async () => {
      const updated = await setTestStatus(testId, status)
      tests.value = tests.value.map((row) => (row.id === testId ? updated : row))
      if (detail.value?.id === testId) detail.value = await fetchTest(testId)
    })
  }

  /**
   * Finish a test, leaving the chosen photo on the card.
   *
   * The chosen photo is installed first, so a failure means the test is still
   * paused or running and the card was left as it was.
   *
   * @param {string} testId Test identifier.
   * @param {string} keepVariantId The photo the card should keep.
   * @returns {Promise<boolean>} Whether the test finished.
   */
  async function finish(testId, keepVariantId) {
    return write(async () => {
      detail.value = await finishTest(testId, keepVariantId)
      const status = detail.value.status
      tests.value = tests.value.map((row) => (row.id === testId ? { ...row, status } : row))
    })
  }

  /**
   * Release every object URL held for the open test.
   *
   * An object URL pins its blob in memory until it is revoked, so leaving a
   * rotation of ten photos behind on every navigation leaks all of them.
   *
   * @returns {void}
   */
  function releaseImages() {
    for (const url of Object.values(imageUrls.value)) URL.revokeObjectURL(url)
    imageUrls.value = {}
  }

  /**
   * Fetch the open test's photos and expose them as object URLs.
   *
   * **In parallel, and with one retry each**, both of which were paid for by a
   * real page. The images live in object storage, the route opens a connection
   * per object, and fetching eleven of them one after another took ten to
   * fifteen seconds — long enough that the timeline drew itself in grey
   * placeholders first. That storage also returns an intermittent 502: probing
   * the same eleven objects failed on all of them once and succeeded on all of
   * them a minute later. A photo dropped on the first attempt therefore stayed
   * missing for as long as the page was open, which is what «седьмая картинка
   * так и не загрузилась» was.
   *
   * The cap is there because the browser serialises past six connections per
   * origin anyway, and a burst of eleven only moves the queue.
   *
   * A photo that fails both attempts is simply absent from the map rather than
   * failing the whole table: the row still carries the metrics, which is most
   * of what the table is for.
   *
   * Runs are generation-guarded, because they OVERLAP. Selecting three files
   * uploads them one after another, each upload replaces the whole detail, and
   * each replacement starts a fresh run — so the run that fetched one photo can
   * finish after the run that fetched three and overwrite it. That is exactly
   * what happened: a three-photo upload left two rows with no thumbnail. A
   * superseded run throws its own URLs away rather than installing them, so
   * losing the race costs nothing and leaks nothing.
   *
   * @param {string} testId Test identifier.
   * @returns {Promise<void>}
   */
  async function loadImages(testId) {
    const run = ++imagesRun
    const queue = [...(detail.value?.variants ?? [])]
    const next = {}

    const worker = async () => {
      for (let variant = queue.shift(); variant; variant = queue.shift()) {
        const blob = await fetchImageTwice(testId, variant.variant_id)
        // Still guard inside the loop: a superseded run should stop spending
        // requests, not just throw the answers away at the end.
        if (run !== imagesRun) return
        if (blob) next[variant.variant_id] = URL.createObjectURL(blob)
      }
    }

    await Promise.all(Array.from({ length: IMAGE_FETCH_LANES }, worker))

    if (run !== imagesRun) {
      for (const url of Object.values(next)) URL.revokeObjectURL(url)
      return
    }
    releaseImages()
    imageUrls.value = next
  }

  /**
   * Change a test's name or rotation trigger, including while it runs.
   *
   * Only the setting the chosen mode uses may travel — see `api.js`. The
   * refreshed test replaces both the list row and the open detail, so the
   * trigger shown on screen is the one the next poll will actually read.
   *
   * @param {string} testId Test identifier.
   * @param {{name?: string, trigger_mode?: 'impressions'|'time'|'either',
   *          impression_budget?: number, slot_minutes?: number}} payload
   * @returns {Promise<boolean>} Whether the change was accepted.
   */
  async function updateSettings(testId, payload) {
    return write(async () => {
      const updated = await updateTestSettings(testId, payload)
      tests.value = tests.value.map((row) => (row.id === testId ? updated : row))
      if (detail.value?.id === testId) detail.value = await fetchTest(testId)
    })
  }

  /**
   * Delete a test and drop it from the list.
   *
   * @param {string} testId Test identifier.
   * @returns {Promise<boolean>} Whether it was deleted.
   */
  async function remove(testId) {
    return write(async () => {
      await deleteTest(testId)
      tests.value = tests.value.filter((row) => row.id !== testId)
      if (detail.value?.id === testId) detail.value = null
    })
  }

  return {
    tests,
    detail,
    imageUrls,
    query,
    skuOptions,
    loading,
    saving,
    error,
    rows,
    canUpload,
    hasMainPhoto,
    remainingSlots,
    uploadedCount,
    loadTests,
    refreshDetail,
    loadTest,
    loadSkuOptions,
    search,
    create,
    addPhoto,
    removePhoto,
    toggleExclusion,
    changeStatus,
    finish,
    updateSettings,
    remove,
    loadImages,
    releaseImages,
  }
})
