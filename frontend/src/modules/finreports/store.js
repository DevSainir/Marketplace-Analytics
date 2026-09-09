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
  downloadCostPricesXlsx,
  fetchBalance,
  fetchCostPrices,
  fetchHarvestState,
  fetchSkuPnl,
  fetchWeeks,
  importCostPricesXlsx,
  saveCostPrices,
  setBalancePin,
  setSkuExclusion,
} from '@/modules/finreports/api'
import {
  DEFAULT_DAYS,
  readSavedPeriod,
  restoreSavedPeriod,
  shiftIsoDate,
  spanDays,
  writeSavedPeriod,
} from '@/modules/finreports/savedPeriod'
import { useHarvestRefresh } from '@/modules/finreports/useHarvestRefresh'

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

  // --- stock balance («Баланс по товарным остаткам») -----------------------
  // Its own period, deliberately: stock is a point-in-time snapshot, so the
  // balance is a picked DAY while the P&L above it is a range.
  const balance = ref(null)
  const balanceDate = ref('')
  const balanceLoading = ref(false)
  const balanceError = ref('')

  // --- report freshness ---------------------------------------------------
  // What the P&L's freshness line is built from: the newest report on file and
  // what the hourly gate found the last time it asked WB for something newer.
  // Deliberately has no `loading` or `error` of its own — the line is a
  // footnote on the statement, and a footnote that fails must go quiet rather
  // than shout over what it annotates.
  const harvestState = ref(null)

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

  /**
   * Read the harvest state for the freshness line.
   *
   * Fired alongside the report rather than after it, and never awaited by
   * anything that renders a figure: this must not gate the numbers. A failure
   * leaves `harvestState` as it was and the line simply does not appear.
   */
  async function loadHarvestState() {
    try {
      const state = await fetchHarvestState()
      harvestState.value = state
      // A harvest in flight is server state, so a reload picks its watcher
      // back up rather than losing track of a run that is still going — and a
      // refresh this browser asked for is reported either way.
      await resumeWatch(state)
    } catch {
      // Silent by design — see above.
    }
  }

  async function loadWeeks() {
    weeksLoading.value = true
    try {
      weeks.value = (await fetchWeeks()).weeks ?? []
      // On a fresh load (page reload resets the store): restore the period the
      // seller last chose, so a reload keeps their view instead of snapping back
      // to a default — for a day, and moved forward if it meant «the latest
      // window» and weeks have landed since (see `restoreSavedPeriod`). With
      // nothing saved we default to the last week: the window a seller checks
      // daily, and far faster to render than 2.5 years of rows.
      if (!dateFrom.value && fullSpan.value) {
        const saved = readSavedPeriod()
        const period = saved
          ? restoreSavedPeriod(saved, fullSpan.value)
          : {
              from: shiftIsoDate(fullSpan.value.date_to, -(DEFAULT_DAYS - 1)),
              to: fullSpan.value.date_to,
            }
        dateFrom.value = period.from
        dateTo.value = period.to
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

  /** Aborts the in-flight balance request when a newer one starts. */
  let balanceRequest = null

  /**
   * Load the stock balance for {@link balanceDate} (newest snapshot when empty).
   *
   * The day is then taken FROM the response rather than assumed: an empty
   * `balanceDate` means «whatever WB last captured», and only the backend knows
   * which day that is.
   */
  async function loadBalance() {
    balanceRequest?.abort()
    const request = new AbortController()
    balanceRequest = request
    balanceLoading.value = true
    balanceError.value = ''
    try {
      const data = await fetchBalance(
        balanceDate.value ? { stat_date: balanceDate.value } : {},
        request.signal,
      )
      if (balanceRequest !== request) return
      balance.value = data
      balanceDate.value = data.stat_date
    } catch (error) {
      if (request.signal.aborted) return
      balanceError.value = extractErrorMessage(error)
    } finally {
      if (balanceRequest === request) {
        balanceRequest = null
        balanceLoading.value = false
      }
    }
  }

  /** Pick another snapshot day and reload the grid. */
  async function setBalanceDate(day) {
    if (!day || day === balanceDate.value) return
    balanceDate.value = day
    await loadBalance()
  }

  /** Which array of the loaded payload each mark kind lives in. */
  const BALANCE_MARKS = {
    sku: 'pinned_skus',
    warehouse: 'pinned_warehouses',
    warehouse_uncounted: 'uncounted_warehouses',
    sku_uncounted: 'uncounted_skus',
  }

  /**
   * Mark a SKU row or warehouse column of the balance grid, or clear the mark.
   *
   * Applied to the loaded payload FIRST and persisted after, with no reload —
   * the grid re-orders and re-totals itself from these arrays, so the click
   * lands instantly (the same behaviour as pinning on the monitoring page,
   * where waiting for a round trip to see a column move felt broken). A failed
   * write is rolled back and surfaced, so the screen never keeps a mark the
   * server rejected.
   */
  async function toggleBalancePin(kind, value, pinned) {
    const field = BALANCE_MARKS[kind]
    if (!field || !balance.value) return
    // Both SKU marks key on a NUMERIC nm_id, the way the backend sends them and
    // the way the rows carry them — a string would never match its row, and the
    // mark would look like it had not applied until the next reload.
    const key = kind.startsWith('sku') ? Number(value) : String(value)
    const before = balance.value[field] ?? []
    balance.value[field] = pinned ? [...before, key] : before.filter((v) => v !== key)
    try {
      await setBalancePin(kind, String(value), pinned)
    } catch (error) {
      if (balance.value) balance.value[field] = before
      balanceError.value = extractErrorMessage(error)
    }
  }

  /** Set an explicit period. Swapped ends are corrected, not rejected. The
   *  choice is persisted — with the harvested span it was made against, which
   *  is what lets a later reload tell «последняя неделя» from a fixed window —
   *  so a page reload restores it. */
  function setPeriod(from, to) {
    if (from && to && from > to) {
      ;[from, to] = [to, from]
    }
    dateFrom.value = from
    dateTo.value = to
    if (from && to) writeSavedPeriod(from, to, fullSpan.value)
  }

  /** Last N settled days (against the newest harvested day, not today). */
  function setPresetDays(days) {
    const end = fullSpan.value?.date_to ?? isoDate(new Date())
    setPeriod(shiftIsoDate(end, -(days - 1)), end)
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

  /**
   * Fetch the per-SKU P&L as an XLSX Blob (the view triggers the download).
   *
   * Exports the whole harvested history so every SKU that ever sold appears with
   * a row to cost — a cost sheet scoped to last week would omit most of them. The
   * weeks are loaded first when the cost page was opened directly, since it is
   * `fullSpan` (derived from them) that bounds «вся история».
   */
  async function exportCostPrices() {
    if (!weeks.value.length) await loadWeeks()
    const span = fullSpan.value
    return downloadCostPricesXlsx(span ? { date_from: span.date_from, date_to: span.date_to } : {})
  }

  /**
   * Import an uploaded workbook, then invalidate the report.
   *
   * Same reasoning as {@link persistCostPrices}: applied costs restate every
   * margin already computed, so the cached report is dropped and the grid
   * reloaded from the persisted truth. Returns the backend's summary so the
   * view can tell the seller how many rows landed and which were skipped.
   */
  async function importCostPrices(file) {
    costsSaving.value = true
    costsError.value = ''
    try {
      const summary = await importCostPricesXlsx(file)
      report.value = null
      await loadCostPrices()
      return summary
    } catch (error) {
      costsError.value = extractErrorMessage(error)
      throw error
    } finally {
      costsSaving.value = false
    }
  }

  /**
   * Reload the harvested weeks and the statement after a harvest brought one.
   *
   * The period follows the new data only for a seller who was looking at the
   * latest week — for them the window they picked *means* «последняя неделя»,
   * and leaving it behind would show a stale week under a fresh report. A
   * deliberately chosen older period is left exactly where it was.
   */
  async function adoptNewReports() {
    const previous = fullSpan.value
    const wasOnLatest = Boolean(dateFrom.value) && dateTo.value === previous?.date_to
    // «Вся история» is followed by extending it, not by sliding it: the window
    // is anchored at both ends, so preserving its LENGTH over a new week would
    // walk its start forward and quietly drop the oldest days from the total.
    const wasWholeHistory = wasOnLatest && dateFrom.value === previous?.date_from
    const days = spanDays(dateFrom.value, dateTo.value)
    await loadWeeks()
    if (wasOnLatest && fullSpan.value && fullSpan.value.date_to !== previous?.date_to) {
      if (wasWholeHistory) setPresetAll()
      else setPresetDays(days)
    }
    await loadReport()
  }

  // The manual «Обновить» trigger. It owns the request and the waiting; the
  // store keeps the one decision that is about the period rather than about
  // harvesting — what a newly arrived week does to the window on screen.
  const { harvestBusy, harvestNotice, harvestError, refreshFromWb, resumeWatch } =
    useHarvestRefresh({
      currentSettled: () => fullSpan.value?.date_to ?? '',
      onNewReports: adoptNewReports,
      // Every poll refreshes the freshness line for free. Without this the line
      // would still describe the situation from before the run the seller just
      // started — and since the button no longer waits, that line IS how they
      // find out what is happening.
      onState: (state) => {
        harvestState.value = state
      },
    })

  return {
    weeks,
    weeksLoading,
    dateFrom,
    dateTo,
    fullSpan,
    report,
    reportLoading,
    reportError,
    balance,
    balanceDate,
    balanceLoading,
    balanceError,
    costPrices,
    costsLoading,
    costsError,
    costsSaving,
    harvestState,
    harvestBusy,
    harvestNotice,
    harvestError,
    refreshFromWb,
    loadHarvestState,
    loadWeeks,
    loadReport,
    toggleExclusion,
    loadBalance,
    setBalanceDate,
    toggleBalancePin,
    setPeriod,
    setPresetDays,
    setPresetAll,
    loadCostPrices,
    persistCostPrices,
    removeCostPrice,
    exportCostPrices,
    importCostPrices,
  }
})
