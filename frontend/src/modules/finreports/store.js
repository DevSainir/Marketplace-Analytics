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
  setSkuExclusion,
} from '@/modules/finreports/api'

/** YYYY-MM-DD in the local calendar (the report dates are calendar days). */
function isoDate(date) {
  const shifted = new Date(date.getTime() - date.getTimezoneOffset() * 60000)
  return shifted.toISOString().slice(0, 10)
}

/** The seller's chosen period survives a reload, kept in localStorage. */
const PERIOD_KEY = 'finreports:period'
/** Default span on first ever open: the last week (7 settled days). */
const DEFAULT_DAYS = 7

function readSavedPeriod() {
  try {
    const raw = localStorage.getItem(PERIOD_KEY)
    const saved = raw ? JSON.parse(raw) : null
    return saved?.from && saved?.to ? saved : null
  } catch {
    return null
  }
}

function writeSavedPeriod(from, to) {
  try {
    localStorage.setItem(PERIOD_KEY, JSON.stringify({ from, to }))
  } catch {
    /* private mode / storage disabled — the period just won't persist */
  }
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
      // On a fresh load (page reload resets the store): restore the period the
      // seller last chose, so a reload keeps their view instead of snapping back
      // to a default. Only when there is nothing saved do we default — to the
      // last week (the window a seller checks daily, and far faster to render
      // than 2.5 years of rows).
      if (!dateFrom.value && fullSpan.value) {
        const saved = readSavedPeriod()
        if (saved) {
          dateFrom.value = saved.from
          dateTo.value = saved.to
        } else {
          const end = new Date(fullSpan.value.date_to)
          const start = new Date(end.getTime() - (DEFAULT_DAYS - 1) * 86400000)
          dateTo.value = fullSpan.value.date_to
          dateFrom.value = isoDate(start)
        }
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

  /**
   * Mark a SKU «Не включать в общий счёт» (or clear it), then reload.
   *
   * The dashboard's «общий счёт» is recomputed on the backend, so after
   * persisting the mark we re-fetch the report rather than adjust totals on the
   * client. The row's own flag is flipped optimistically so the checkbox reacts
   * immediately; the reload then brings the recomputed dashboard.
   */
  async function toggleExclusion(nmId, excluded) {
    const row = report.value?.rows?.find((r) => r.nm_id === nmId)
    if (row) row.is_excluded = excluded
    let failure = ''
    try {
      await setSkuExclusion(nmId, excluded)
    } catch (error) {
      failure = extractErrorMessage(error)
    }
    // Reload regardless, to resync from the persisted truth (the mark may not
    // have applied). Surface the failure *after* — loadReport clears the error
    // channel on entry, so setting it before would be wiped out.
    await loadReport()
    if (failure) reportError.value = failure
  }

  /** Set an explicit period. Swapped ends are corrected, not rejected. The
   *  choice is persisted so a page reload restores it. */
  function setPeriod(from, to) {
    if (from && to && from > to) {
      ;[from, to] = [to, from]
    }
    dateFrom.value = from
    dateTo.value = to
    if (from && to) writeSavedPeriod(from, to)
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
    toggleExclusion,
    setPeriod,
    setPresetDays,
    setPresetAll,
    loadCostPrices,
    persistCostPrices,
    removeCostPrice,
  }
})
