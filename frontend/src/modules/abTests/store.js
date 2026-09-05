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
  setTestStatus,
  updateTestSettings,
  uploadVariant,
} from '@/modules/abTests/api'

/** Statuses as the backend spells them, with their Russian labels. */
export const STATUS_LABELS = {
  draft: 'Черновик',
  running: 'Запущен',
  paused: 'На паузе',
  completed: 'Завершён',
  cancelled: 'Отменён',
}

/** Product cap on photos in one rotation; mirrors the backend's own limit. */
export const MAX_VARIANTS = 10

export const useAbTestsStore = defineStore('abTests', () => {
  const tests = ref([])
  const detail = ref(null)
  // variant_id -> object URL. The images are authenticated, so they are
  // fetched as blobs and handed to `<img>` as object URLs; the browser would
  // send neither the access token nor the workspace header on its own.
  const imageUrls = ref({})
  const query = ref('')
  const loading = ref(false)
  const saving = ref(false)
  const error = ref('')

  let listController = null

  /** Tests as the list renders them (the backend already ordered them). */
  const rows = computed(() => tests.value)

  /** True while the open test still has room for another photo. */
  const canUpload = computed(() => !!detail.value && detail.value.variants.length < MAX_VARIANTS)

  /** How many more photos the open test accepts. */
  const remainingSlots = computed(() =>
    detail.value ? Math.max(0, MAX_VARIANTS - detail.value.variants.length) : 0,
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
   * @returns {Promise<boolean>} Whether it was accepted.
   */
  async function addPhoto(testId, file) {
    saving.value = true
    error.value = ''
    try {
      detail.value = await uploadVariant(testId, file)
      return true
    } catch (err) {
      error.value = extractErrorMessage(err)
      return false
    } finally {
      saving.value = false
    }
  }

  /**
   * Remove a photo from the open test.
   *
   * @param {string} testId Test identifier.
   * @param {string} variantId Variant identifier.
   * @returns {Promise<boolean>} Whether it was removed.
   */
  async function removePhoto(testId, variantId) {
    saving.value = true
    error.value = ''
    try {
      await deleteVariant(testId, variantId)
      detail.value = await fetchTest(testId)
      return true
    } catch (err) {
      error.value = extractErrorMessage(err)
      return false
    } finally {
      saving.value = false
    }
  }

  /**
   * Start, pause or cancel a test.
   *
   * Starting installs the first photo on the seller's card, so a failure here
   * is shown rather than swallowed: the card was not touched.
   *
   * @param {string} testId Test identifier.
   * @param {'running'|'paused'|'cancelled'} status Target status.
   * @returns {Promise<boolean>} Whether the transition happened.
   */
  async function changeStatus(testId, status) {
    saving.value = true
    error.value = ''
    try {
      const updated = await setTestStatus(testId, status)
      tests.value = tests.value.map((row) => (row.id === testId ? updated : row))
      if (detail.value?.id === testId) detail.value = await fetchTest(testId)
      return true
    } catch (err) {
      error.value = extractErrorMessage(err)
      return false
    } finally {
      saving.value = false
    }
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
   * A photo that fails to load is simply absent from the map rather than
   * failing the whole table: the row still carries the metrics, which is most
   * of what the table is for.
   *
   * @param {string} testId Test identifier.
   * @returns {Promise<void>}
   */
  async function loadImages(testId) {
    const variants = detail.value?.variants ?? []
    const next = {}
    for (const variant of variants) {
      try {
        next[variant.variant_id] = URL.createObjectURL(
          await fetchVariantImage(testId, variant.variant_id),
        )
      } catch {
        // Left out of the map; the row renders without its thumbnail.
      }
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
   * @param {{name?: string, trigger_mode?: 'impressions'|'time',
   *          impression_budget?: number, slot_minutes?: number}} payload
   * @returns {Promise<boolean>} Whether the change was accepted.
   */
  async function updateSettings(testId, payload) {
    saving.value = true
    error.value = ''
    try {
      const updated = await updateTestSettings(testId, payload)
      tests.value = tests.value.map((row) => (row.id === testId ? updated : row))
      if (detail.value?.id === testId) detail.value = await fetchTest(testId)
      return true
    } catch (err) {
      error.value = extractErrorMessage(err)
      return false
    } finally {
      saving.value = false
    }
  }

  /**
   * Delete a test and drop it from the list.
   *
   * @param {string} testId Test identifier.
   * @returns {Promise<boolean>} Whether it was deleted.
   */
  async function remove(testId) {
    saving.value = true
    error.value = ''
    try {
      await deleteTest(testId)
      tests.value = tests.value.filter((row) => row.id !== testId)
      if (detail.value?.id === testId) detail.value = null
      return true
    } catch (err) {
      error.value = extractErrorMessage(err)
      return false
    } finally {
      saving.value = false
    }
  }

  return {
    tests,
    detail,
    imageUrls,
    query,
    loading,
    saving,
    error,
    rows,
    canUpload,
    remainingSlots,
    loadTests,
    loadTest,
    search,
    create,
    addPhoto,
    removePhoto,
    changeStatus,
    updateSettings,
    remove,
    loadImages,
    releaseImages,
  }
})
