/**
 * Monitoring Pinia store (Composition-API setup style).
 *
 * Owns all data fetching for the module; views stay declarative and
 * components stay dumb. `currentProduct` mirrors the backend
 * `SkuDetailResponse` shape 1:1.
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { extractErrorMessage } from '@/core/api/axios'
import { fetchSkuDetail, fetchSkuSummary, lookupSkus } from '@/modules/monitoring/api'

export const useMonitoringStore = defineStore('monitoring', () => {
  // --- state -------------------------------------------------------------
  const loading = ref(false)
  const error = ref(null)
  const currentProduct = ref(null)
  /** The searched query when the lookup legitimately matched nothing (not a failure). */
  const notFound = ref(null)
  /** Ambiguous vendor-code search results awaiting the user's choice. */
  const lookupMatches = ref([])

  // The per-SKU summary listing that feeds the search dropdown. Scoped to the
  // selected window, NOT to the detail search — reset() leaves it intact.
  const skuList = ref([])
  const skuListLoading = ref(false)
  const skuListError = ref(null)

  // Window/filter params of the latest search, reused when the user picks one
  // of several vendor-code matches.
  let lastParams = {}

  // Monotonic id per search; responses arriving for an older id are stale
  // (the user has already searched again) and must not overwrite state.
  let requestSeq = 0

  // Controller of the in-flight search; each new search (and reset) aborts it
  // so stale requests release the network instead of just being ignored.
  let activeController = null

  // --- getters -----------------------------------------------------------
  // Funnel window totals come precomputed from the backend (`funnel_totals`).
  /** Add-to-cart events over the window. */
  const totalCarts = computed(() => currentProduct.value?.funnel_totals?.cart_count ?? 0)

  /** Raw orders over the window. */
  const totalOrders = computed(() => currentProduct.value?.funnel_totals?.order_count ?? 0)

  /** Advertising clicks over the window, summed across campaigns. */
  const totalAdClicks = computed(() =>
    (currentProduct.value?.advertising ?? []).reduce((sum, c) => sum + c.clicks, 0),
  )

  /** Advertising spend over the window, summed across campaigns (₽). */
  const totalAdSpend = computed(() =>
    (currentProduct.value?.advertising ?? []).reduce((sum, c) => sum + c.spend, 0),
  )

  const isOutOfStock = computed(() => (currentProduct.value?.stock?.total_quantity ?? 0) === 0)

  // --- actions -----------------------------------------------------------
  /** Axios abort rejections are silent: they only mean a newer search won. */
  function isAbortError(err) {
    return err?.code === 'ERR_CANCELED' || err?.name === 'CanceledError'
  }

  /**
   * Resolve a vendor code (or fragment) to a single nm ID.
   *
   * Pure lookup — NO state writes here: the result is discriminated so that
   * `fetchProductData` applies it only after re-checking the request sequence
   * (a slow lookup must never clobber a newer search).
   *
   * @returns {Promise<
   *   | {kind: 'resolved', nmId: number}
   *   | {kind: 'not-found'}
   *   | {kind: 'ambiguous', items: object[]}
   * >}
   */
  async function resolveVendorCode(query, signal) {
    const result = await lookupSkus(query, signal)
    if (!result.count) return { kind: 'not-found' }
    const exact = result.items.find(
      (item) => item.vendor_code.toLowerCase() === query.toLowerCase(),
    )
    if (exact) return { kind: 'resolved', nmId: exact.nm_id }
    if (result.count === 1) return { kind: 'resolved', nmId: result.items[0].nm_id }
    return { kind: 'ambiguous', items: result.items }
  }

  /**
   * Load the full detail view for one SKU into `currentProduct`.
   *
   * @param {number|string} sku WB nm ID or a vendor code / fragment
   *   (e.g. "M-TRX01-BLK"); vendor codes are resolved via the lookup endpoint.
   * @param {{date_from?: string, date_to?: string, campaign_id?: number, campaign_status?: string}} [params]
   */
  async function fetchProductData(sku, params = lastParams) {
    const query = String(sku).trim()
    if (!query) return

    const seq = ++requestSeq
    activeController?.abort()
    const controller = new AbortController()
    activeController = controller

    lastParams = params
    loading.value = true
    error.value = null
    notFound.value = null
    lookupMatches.value = []
    try {
      let nmId = /^\d+$/.test(query) ? Number(query) : null
      if (nmId === null) {
        const resolution = await resolveVendorCode(query, controller.signal)
        if (seq !== requestSeq) return // a newer search superseded this one
        if (resolution.kind === 'not-found') {
          currentProduct.value = null
          notFound.value = query
          return
        }
        if (resolution.kind === 'ambiguous') {
          currentProduct.value = null
          lookupMatches.value = resolution.items
          return
        }
        nmId = resolution.nmId
      }
      const detail = await fetchSkuDetail(nmId, params, controller.signal)
      if (seq !== requestSeq) return
      currentProduct.value = detail
    } catch (err) {
      if (seq !== requestSeq || isAbortError(err)) return
      currentProduct.value = null
      error.value = extractErrorMessage(err)
    } finally {
      if (seq === requestSeq) loading.value = false
      if (activeController === controller) activeController = null
    }
  }

  // Controller of the in-flight list fetch; independent from the detail search
  // so refreshing the dropdown never cancels a running SKU analysis.
  let listController = null

  /**
   * Load the per-SKU summary listing for the window into `skuList`.
   *
   * @param {{date_from?: string, date_to?: string}} [params]
   */
  async function fetchSkuList(params = {}) {
    listController?.abort()
    const controller = new AbortController()
    listController = controller

    skuListLoading.value = true
    skuListError.value = null
    try {
      // One page of 500 covers the whole catalogue for now; pagination can
      // come back when the assortment outgrows it.
      const result = await fetchSkuSummary({ ...params, limit: 500 }, controller.signal)
      skuList.value = result.items
    } catch (err) {
      if (isAbortError(err)) return
      skuList.value = []
      skuListError.value = extractErrorMessage(err)
    } finally {
      if (listController === controller) {
        skuListLoading.value = false
        listController = null
      }
    }
  }

  /** Load one of several vendor-code matches, keeping the searched window. */
  function selectSku(nmId) {
    return fetchProductData(nmId)
  }

  /** Back to the pristine state (e.g. the URL query was cleared); aborts any in-flight search. */
  function reset() {
    requestSeq += 1 // in-flight responses become stale
    activeController?.abort()
    activeController = null
    lastParams = {}
    loading.value = false
    error.value = null
    notFound.value = null
    currentProduct.value = null
    lookupMatches.value = []
  }

  return {
    loading,
    error,
    notFound,
    currentProduct,
    lookupMatches,
    skuList,
    skuListLoading,
    skuListError,
    fetchSkuList,
    selectSku,
    totalCarts,
    totalAdClicks,
    totalOrders,
    totalAdSpend,
    isOutOfStock,
    fetchProductData,
    reset,
  }
})
