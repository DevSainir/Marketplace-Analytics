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
import { computed, ref, shallowRef } from 'vue'

import { extractErrorMessage } from '@/core/api/axios'
import { presetWindow } from '@/core/utils/calendarModel'
import { isoDaysAgo } from '@/core/utils/dates'
import { recallPeriod, rememberPeriod } from '@/core/utils/periodMemory'
import { fetchSummary, fetchSummarySpan } from '@/modules/summary/api'
import { useGroupCut } from '@/modules/heatmap'
import { buildCategories } from '@/modules/summary/categories'

/** Default window, matching the backend's own: the last week. */
const DEFAULT_DAYS = 7

/**
 * Longest window the summary answers for, both ends counted — the backend's
 * `MAX_WINDOW_DAYS` (1200 days between the ends), so the calendar can grey out
 * what the API would refuse.
 */
export const MAX_PERIOD_DAYS = 1201

/** This page's key in `periodMemory`. */
const PERIOD_PAGE = 'summary'

export const useSummaryStore = defineStore('summary', () => {
  const initial = presetWindow(DEFAULT_DAYS, { end: isoDaysAgo(0) })

  const dateFrom = ref(initial.from)
  const dateTo = ref(initial.to)

  // --- presentation, answered without a request ---------------------------
  // The seller's own price, not the after-СПП one: WB funds the СПП gap, so
  // this is the figure the payout is pegged to and the one a seller plans on.
  const revenueBase = ref('seller')
  const cut = ref('sku')
  const sort = ref('revenue')
  const { groups, readable: groupsReadable } = useGroupCut(cut)

  // Shallow: the payload is only ever replaced whole, never edited in place,
  // and a deep proxy over every row is work done on the page's own thread
  // exactly while it is busy taking the response in.
  const data = shallowRef(null)
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
      groups: groups.value,
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
      // The window already on screen stays: a failed reload is a line above
      // it, not a blank page.
      error.value = extractErrorMessage(cause)
    } finally {
      if (inFlight === controller) {
        inFlight = null
        loading.value = false
      }
    }
  }

  /** The settled span as `periodMemory` takes it. */
  const periodEdge = () => ({ from: span.value?.date_from, to: span.value?.date_to })

  /**
   * Learn which days are settled, then open on the period left an hour ago or,
   * failing that, on the last week of them.
   *
   * Fired before the first load so the calendar knows its bounds; its failure
   * is swallowed, because a picker without a span still works against today
   * and a summary must not be gated on it.
   */
  async function init() {
    try {
      span.value = await fetchSummarySpan()
      if (span.value?.date_to) {
        const period =
          recallPeriod(PERIOD_PAGE, periodEdge()) ??
          presetWindow(DEFAULT_DAYS, {
            end: span.value.date_to,
            historyFrom: span.value.date_from,
          })
        dateFrom.value = period.from
        dateTo.value = period.to
      }
    } catch {
      span.value = null
    }
    return load()
  }

  /** Move the window, remember it for an hour, and reload. */
  function setPeriod(from, to) {
    if (from === dateFrom.value && to === dateTo.value) return
    dateFrom.value = from
    dateTo.value = to
    rememberPeriod(PERIOD_PAGE, from, to, periodEdge())
    return load()
  }

  return {
    dateFrom,
    dateTo,
    revenueBase,
    cut,
    groupsReadable,
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
    init,
    load,
    setPeriod,
  }
})
