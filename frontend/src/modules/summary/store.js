/**
 * Summary Pinia store (Composition-API setup style).
 *
 * One window, one request, one object on screen. The store exists rather than
 * the view fetching for itself because three controls — the period, the price
 * base and the category cut — all reload the same figures, and a page that
 * fired three overlapping requests would settle on whichever answered last.
 * Every fetch aborts the one before it.
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { extractErrorMessage } from '@/core/api/axios'
import { fetchSummary } from '@/modules/summary/api'

/** Default window, matching the backend's own: the last four settlement weeks. */
const DEFAULT_DAYS = 28

/** YYYY-MM-DD in the local calendar (settlement dates are calendar days). */
function isoDate(date) {
  const shifted = new Date(date.getTime() - date.getTimezoneOffset() * 60000)
  return shifted.toISOString().slice(0, 10)
}

/** `days` back from today, as an inclusive ISO pair. */
function defaultWindow(days = DEFAULT_DAYS) {
  const end = new Date()
  const start = new Date(end.getTime() - days * 86400000)
  return { from: isoDate(start), to: isoDate(end) }
}

export const useSummaryStore = defineStore('summary', () => {
  const initial = defaultWindow()

  const dateFrom = ref(initial.from)
  const dateTo = ref(initial.to)
  const revenueBase = ref('paid')
  const grouping = ref('sku')

  const data = ref(null)
  const loading = ref(false)
  const error = ref('')

  let inFlight = null

  const kpi = computed(() => data.value?.kpi ?? null)
  const days = computed(() => data.value?.days ?? [])
  const categories = computed(() => data.value?.categories ?? [])
  const currency = computed(() => data.value?.currency ?? '')

  /**
   * Whether the margin is available at all for this window.
   *
   * A window with any uncosted SKU reports no margin — deliberately, so a month
   * of implicitly free goods cannot read as a good one. The page says so rather
   * than drawing an empty line and letting the reader guess.
   */
  const marginBlocked = computed(() => Boolean(kpi.value && kpi.value.margin === null))

  /** Load the window. Aborts any request still running. */
  async function load() {
    inFlight?.abort()
    const controller = new AbortController()
    inFlight = controller
    loading.value = true
    error.value = ''
    try {
      data.value = await fetchSummary(
        {
          date_from: dateFrom.value,
          date_to: dateTo.value,
          revenue_base: revenueBase.value,
          grouping: grouping.value,
        },
        controller.signal,
      )
    } catch (cause) {
      if (controller.signal.aborted) return
      error.value = extractErrorMessage(cause)
      data.value = null
    } finally {
      if (inFlight === controller) {
        inFlight = null
        loading.value = false
      }
    }
  }

  /** Move the window and reload. */
  function setPeriod(from, to) {
    if (from === dateFrom.value && to === dateTo.value) return
    dateFrom.value = from
    dateTo.value = to
    return load()
  }

  /** Jump to a preset window ending today. */
  function setPresetDays(days_) {
    const { from, to } = defaultWindow(days_)
    return setPeriod(from, to)
  }

  /** Switch the price revenue is denominated in, and reload. */
  function setRevenueBase(base) {
    if (base === revenueBase.value) return
    revenueBase.value = base
    return load()
  }

  /** Switch how «Выручка по категории» is cut, and reload. */
  function setGrouping(next) {
    if (next === grouping.value) return
    grouping.value = next
    return load()
  }

  return {
    dateFrom,
    dateTo,
    revenueBase,
    grouping,
    data,
    loading,
    error,
    kpi,
    days,
    categories,
    currency,
    marginBlocked,
    load,
    setPeriod,
    setPresetDays,
    setRevenueBase,
    setGrouping,
  }
})
