/**
 * The monitoring sandbox's store — /labs/monitoring on the workspace's own data.
 *
 * The sandbox exists to compare a second design system against /monitoring, and
 * that comparison only means something when both pages show the same numbers.
 * It used to render synthesised fixtures; since 2026-10-22 it reads the same
 * endpoints the real page does (`labs/api.js`), so on the demo it shows the demo
 * shop and on a real workspace that workspace.
 *
 * Read-only on purpose. Every editing control on the page stays a sink: the
 * sandbox is for looking, and a second place that can write a workspace's matrix
 * would be a second place to get it wrong. Its own Pinia id, so it never shares
 * state with the real page.
 *
 * Besides the window on screen it loads one LONG window of the same SKU — a
 * year — for the chart that shows how the chart copes with one.
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

import { extractErrorMessage } from '@/core/api/axios'
import { presetWindow } from '@/core/utils/calendarModel'
import { isoDaysAgo } from '@/core/utils/dates'
import {
  fetchPinnedSkus,
  fetchSkuDetail,
  fetchSkuSummary,
  fetchStockRange,
} from '@/modules/labs/api'

/** The window the page opens on: thirty days, as /monitoring does. */
const DEFAULT_DAYS = 30

/** The long chart's window: a year, the longest the detail endpoint answers. */
const LONG_DAYS = 365

export const useLabMonitoringStore = defineStore('labMonitoring', () => {
  const initial = presetWindow(DEFAULT_DAYS, { end: isoDaysAgo(0) })
  const dateFrom = ref(initial.from)
  const dateTo = ref(initial.to)

  const skuList = ref([])
  const pinnedSkus = ref([])
  const selectedId = ref(null)
  const product = ref(null)
  const longProduct = ref(null)
  const stockDays = ref([])
  const loading = ref(false)
  const error = ref('')
  let inFlight = null

  /** The SKU list for the window, and the pins (decoration: a failure is an empty row). */
  async function loadCatalogue() {
    const params = { date_from: dateFrom.value, date_to: dateTo.value, limit: 500 }
    const [summary, pins] = await Promise.all([
      fetchSkuSummary(params),
      fetchPinnedSkus().catch(() => ({ items: [] })),
    ])
    skuList.value = summary.items
    pinnedSkus.value = pins.items
  }

  /** Load one SKU: the window on screen, its stock, and the long window. */
  async function select(nmId) {
    if (!nmId) return
    inFlight?.abort()
    const controller = new AbortController()
    inFlight = controller
    selectedId.value = nmId
    loading.value = true
    error.value = ''
    const window = { date_from: dateFrom.value, date_to: dateTo.value }
    const long = presetWindow(LONG_DAYS, { end: isoDaysAgo(0) })
    try {
      const [detail, stock, longDetail] = await Promise.all([
        fetchSkuDetail(nmId, window, controller.signal),
        fetchStockRange(nmId, window, controller.signal),
        fetchSkuDetail(nmId, { date_from: long.from, date_to: long.to }, controller.signal),
      ])
      product.value = detail
      stockDays.value = stock.days
      longProduct.value = longDetail
    } catch (cause) {
      if (controller.signal.aborted) return
      error.value = extractErrorMessage(cause)
    } finally {
      if (inFlight === controller) {
        inFlight = null
        loading.value = false
      }
    }
  }

  /** First visit: the catalogue, then the first pinned SKU (or the first listed). */
  async function init() {
    try {
      await loadCatalogue()
    } catch (cause) {
      error.value = extractErrorMessage(cause)
      return
    }
    await select(selectedId.value ?? pinnedSkus.value[0]?.nm_id ?? skuList.value[0]?.nm_id)
  }

  /** A new window: reload the list and the SKU on screen. */
  async function setPeriod({ from, to }) {
    dateFrom.value = from
    dateTo.value = to
    await init()
  }

  return {
    dateFrom,
    dateTo,
    skuList,
    pinnedSkus,
    selectedId,
    product,
    longProduct,
    stockDays,
    loading,
    error,
    init,
    select,
    setPeriod,
  }
})
