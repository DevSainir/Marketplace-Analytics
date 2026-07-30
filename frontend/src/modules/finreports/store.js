/**
 * FinReports Pinia store (Composition-API setup style).
 *
 * Owns the module's fetching so the views stay declarative. It exists rather
 * than each view fetching for itself because the two pages are coupled in one
 * direction that matters: saving a cost price changes every margin on the
 * report, so the editor invalidates the P&L instead of leaving a stale profit
 * on screen behind a route change.
 *
 * The period is an arbitrary ``{dateFrom, dateTo}`` pair, not a week id: the
 * report aggregates whatever settlement rows fall inside it, so any range the
 * seller can type is a valid period. The harvested weeks are still loaded —
 * they bound the «вся история» preset.
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { extractErrorMessage } from '@/core/api/axios'
import {
  deleteCostPrice,
  fetchCostPrices,
  fetchSkuPnl,
  fetchWeeks,
  saveCostPrices,
} from '@/modules/finreports/api'

/** YYYY-MM-DD in the local calendar (the report dates are calendar days). */
function isoDate(date) {
  const shifted = new Date(date.getTime() - date.getTimezoneOffset() * 60000)
  return shifted.toISOString().slice(0, 10)
}

export const useFinReportsStore = defineStore('finreports', () => {
  // --- period selection ---------------------------------------------------
  const weeks = ref([])
  const weeksLoading = ref(false)
  const dateFrom = ref('')
  const dateTo = ref('')

  // --- per-SKU report -----------------------------------------------------
  const report = ref(null)
  const reportLoading = ref(false)
  const reportError = ref('')

  // --- cost prices --------------------------------------------------------
  const costPrices = ref(null)
  const costsLoading = ref(false)
  const costsError = ref('')
  const costsSaving = ref(false)

  /** The full harvested span, for the «вся история» preset. */
  const fullSpan = computed(() => {
    if (!weeks.value.length) return null
    return {
      date_from: weeks.value.reduce((a, w) => (a < w.date_from ? a : w.date_from), '9999'),
      date_to: weeks.value.reduce((a, w) => (a > w.date_to ? a : w.date_to), '0000'),
    }
  })

  async function loadWeeks() {
    weeksLoading.value = true
    try {
      weeks.value = (await fetchWeeks()).weeks ?? []
      // First open: default to the last ~30 settled days, not the whole
      // history — the recent window is what a seller checks daily, and it
      // renders an order of magnitude faster than 2.5 years of rows.
      if (!dateFrom.value && fullSpan.value) {
        const end = new Date(fullSpan.value.date_to)
        const start = new Date(end.getTime() - 29 * 86400000)
        dateTo.value = fullSpan.value.date_to
        dateFrom.value = isoDate(start)
      }
    } catch (error) {
      reportError.value = extractErrorMessage(error)
    } finally {
      weeksLoading.value = false
    }
  }

  /** Aborts the in-flight report request when a newer one starts. */
  let reportRequest = null

  async function loadReport() {
    if (!dateFrom.value || !dateTo.value) return
    // A whole-history request takes seconds over 620k rows, so switching the
    // period twice in quick succession genuinely overlaps. Without this, a
    // slow response for the OLD period can land after the new one and leave
    // the page showing figures for a period the picker no longer names.
    reportRequest?.abort()
    const request = new AbortController()
    reportRequest = request
    reportLoading.value = true
    reportError.value = ''
    try {
      const data = await fetchSkuPnl(
        { date_from: dateFrom.value, date_to: dateTo.value },
        request.signal,
      )
      if (reportRequest !== request) return
      report.value = data
    } catch (error) {
      if (request.signal.aborted) return
      reportError.value = extractErrorMessage(error)
    } finally {
      if (reportRequest === request) {
        reportRequest = null
        reportLoading.value = false
      }
    }
  }

  /** Set an explicit period. Swapped ends are corrected, not rejected. */
  function setPeriod(from, to) {
    if (from && to && from > to) {
      ;[from, to] = [to, from]
    }
    dateFrom.value = from
    dateTo.value = to
  }

  /** Last N settled days (against the newest harvested day, not today). */
  function setPresetDays(days) {
    const end = fullSpan.value?.date_to ?? isoDate(new Date())
    const start = new Date(new Date(end).getTime() - (days - 1) * 86400000)
    setPeriod(isoDate(start), end)
  }

  /** The whole harvested history. */
  function setPresetAll() {
    if (fullSpan.value) setPeriod(fullSpan.value.date_from, fullSpan.value.date_to)
  }

  async function loadCostPrices() {
    costsLoading.value = true
    costsError.value = ''
    try {
      costPrices.value = await fetchCostPrices()
    } catch (error) {
      costsError.value = extractErrorMessage(error)
    } finally {
      costsLoading.value = false
    }
  }

  /**
   * Persist edited costs, then drop the cached report.
   *
   * Dropping it is the point: a saved cost restates every margin already on
   * screen, and showing the old one next to the new cost is the kind of quiet
   * inconsistency a seller would act on.
   */
  async function persistCostPrices(items) {
    costsSaving.value = true
    costsError.value = ''
    try {
      const result = await saveCostPrices(items)
      report.value = null
      await loadCostPrices()
      return result
    } catch (error) {
      costsError.value = extractErrorMessage(error)
      throw error
    } finally {
      costsSaving.value = false
    }
  }

  async function removeCostPrice(nmId) {
    costsSaving.value = true
    costsError.value = ''
    try {
      await deleteCostPrice(nmId)
      report.value = null
      await loadCostPrices()
    } catch (error) {
      costsError.value = extractErrorMessage(error)
      throw error
    } finally {
      costsSaving.value = false
    }
  }

  return {
    weeks,
    weeksLoading,
    dateFrom,
    dateTo,
    fullSpan,
    report,
    reportLoading,
    reportError,
    costPrices,
    costsLoading,
    costsError,
    costsSaving,
    loadWeeks,
    loadReport,
    setPeriod,
    setPresetDays,
    setPresetAll,
    loadCostPrices,
    persistCostPrices,
    removeCostPrice,
  }
})
