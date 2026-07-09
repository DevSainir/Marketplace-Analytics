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
import { fetchSkuDetail, lookupSkus } from '@/modules/monitoring/api'

export const useMonitoringStore = defineStore('monitoring', () => {
  // --- state -------------------------------------------------------------
  const loading = ref(false)
  const error = ref(null)
  const currentProduct = ref(null)
  /** Ambiguous vendor-code search results awaiting the user's choice. */
  const lookupMatches = ref([])

  // Window/filter params of the latest search, reused when the user picks one
  // of several vendor-code matches.
  let lastParams = {}

  // Monotonic id per search; responses arriving for an older id are stale
  // (the user has already searched again) and must not overwrite state.
  let requestSeq = 0

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
  /**
   * Resolve a vendor code (or fragment) to a single nm ID.
   *
   * Exact match wins; a single hit is used as-is; several hits are exposed via
   * `lookupMatches` for the user to pick from (returns null in that case).
   */
  async function resolveVendorCode(query) {
    const result = await lookupSkus(query)
    if (!result.count) {
      currentProduct.value = null
      error.value = `По артикулу «${query}» ничего не найдено.`
      return null
    }
    const exact = result.items.find(
      (item) => item.vendor_code.toLowerCase() === query.toLowerCase(),
    )
    if (exact) return exact.nm_id
    if (result.count === 1) return result.items[0].nm_id
    lookupMatches.value = result.items
    currentProduct.value = null
    return null
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
    lastParams = params
    loading.value = true
    error.value = null
    lookupMatches.value = []
    try {
      const nmId = /^\d+$/.test(query) ? Number(query) : await resolveVendorCode(query)
      if (seq !== requestSeq) return // a newer search superseded this one
      if (nmId !== null) {
        const detail = await fetchSkuDetail(nmId, params)
        if (seq !== requestSeq) return
        currentProduct.value = detail
      }
    } catch (err) {
      if (seq !== requestSeq) return
      currentProduct.value = null
      error.value = extractErrorMessage(err)
    } finally {
      if (seq === requestSeq) loading.value = false
    }
  }

  /** Load one of several vendor-code matches, keeping the searched window. */
  function selectSku(nmId) {
    return fetchProductData(nmId)
  }

  return {
    loading,
    error,
    currentProduct,
    lookupMatches,
    selectSku,
    totalCarts,
    totalAdClicks,
    totalOrders,
    totalAdSpend,
    isOutOfStock,
    fetchProductData,
  }
})
