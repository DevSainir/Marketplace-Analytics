/**
 * Summary Pinia store (Composition-API setup style).
 *
 * One window, one request. The period is the ONLY thing that costs a round
 * trip: the price base, how the category block is cut, how it is sorted and how
 * much of its tail is folded are all answered from the payload, which carries
 * both bases and every article row. They used to be query parameters, and each
 * click on one meant re-aggregating the whole settlement window on the server —
 * seconds of waiting for arithmetic over a few dozen rows.
 *
 * Presets end on the newest SETTLED day rather than today. «30 дней» measured to
 * today would include days no WB report covers yet and read as a collapse in
 * sales.
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { extractErrorMessage } from '@/core/api/axios'
import { fetchSummary, fetchSummarySpan } from '@/modules/summary/api'
import { buildCategories } from '@/modules/summary/categories'

/** Default window, matching the backend's own: the last four settlement weeks. */
const DEFAULT_DAYS = 28

/** YYYY-MM-DD in the local calendar (settlement dates are calendar days). */
function isoDate(date) {
  const shifted = new Date(date.getTime() - date.getTimezoneOffset() * 60000)
  return shifted.toISOString().slice(0, 10)
}

/** `days` back from `end` (inclusive), as an ISO pair. */
function windowEnding(end, days) {
  const last = new Date(`${end}T00:00:00`)
  return { from: isoDate(new Date(last.getTime() - (days - 1) * 86400000)), to: end }
}

export const useSummaryStore = defineStore('summary', () => {
  const today = isoDate(new Date())
  const initial = windowEnding(today, DEFAULT_DAYS)

  const dateFrom = ref(initial.from)
  const dateTo = ref(initial.to)

  // --- presentation, answered without a request ---------------------------
  // The seller's own price, not the after-СПП one: WB funds the СПП gap, so
  // this is the figure the payout is pegged to and the one a seller plans on.
  const revenueBase = ref('seller')
  const cut = ref('sku')
  const sort = ref('revenue')

  const data = ref(null)
  const span = ref(null)
  const loading = ref(false)
  const error = ref('')

  let inFlight = null

  const kpi = computed(() => data.value?.kpi ?? null)
  const days = computed(() => data.value?.days ?? [])
  const currency = computed(() => data.value?.currency ?? '')

  /** The bars, folded and ranked in the browser. */
  const categories = computed(() =>
    buildCategories(data.value?.rows ?? [], {
      cut: cut.value,
      base: revenueBase.value,
      sort: sort.value,
    }),
  )

  /**
   * Whether the margin is available at all for this window.
   *
   * A window with any uncosted article reports no margin — deliberately, so a
   * month of implicitly free goods cannot read as a good one.
   */
  const marginBlocked = computed(() => Boolean(kpi.value && kpi.value.margin === null))

  /** Revenue at the selected base, for the cards and the chart. */
  const revenue = computed(() => {
    if (!kpi.value) return 0
    return Number(
      revenueBase.value === 'seller' ? kpi.value.revenue_seller : kpi.value.revenue_paid,
    )
  })

  /** Load the window. Aborts any request still running. */
  async function load() {
    inFlight?.abort()
    const controller = new AbortController()
    inFlight = controller
    loading.value = true
    error.value = ''
    try {
      data.value = await fetchSummary(
        { date_from: dateFrom.value, date_to: dateTo.value },
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

  /**
   * Learn which days are settled, then open on the last four weeks of them.
   *
   * Fired before the first load so the presets and «Вся история» know what they
   * mean; its failure is swallowed, because a picker without a span still works
   * against today and a summary must not be gated on it.
   */
  async function init() {
    try {
      span.value = await fetchSummarySpan()
      if (span.value?.date_to) {
        const period = windowEnding(span.value.date_to, DEFAULT_DAYS)
        dateFrom.value = period.from
        dateTo.value = period.to
      }
    } catch {
      span.value = null
    }
    return load()
  }

  /** Move the window and reload. */
  function setPeriod(from, to) {
    if (from === dateFrom.value && to === dateTo.value) return
    dateFrom.value = from
    dateTo.value = to
    return load()
  }

  /** Last N settled days, ending on the newest day WB has calculated. */
  function setPresetDays(days_) {
    const end = span.value?.date_to ?? isoDate(new Date())
    const period = windowEnding(end, days_)
    return setPeriod(period.from, period.to)
  }

  /** Everything WB has ever settled for this кабинет. */
  function setPresetAll() {
    if (!span.value?.date_from || !span.value?.date_to) return
    return setPeriod(span.value.date_from, span.value.date_to)
  }

  /** True when the window is exactly the full settled span. */
  const isAllHistory = computed(
    () =>
      Boolean(span.value?.date_from) &&
      dateFrom.value === span.value.date_from &&
      dateTo.value === span.value.date_to,
  )

  return {
    dateFrom,
    dateTo,
    revenueBase,
    cut,
    sort,
    data,
    span,
    loading,
    error,
    kpi,
    days,
    categories,
    currency,
    marginBlocked,
    revenue,
    isAllHistory,
    init,
    load,
    setPeriod,
    setPresetDays,
    setPresetAll,
  }
})
