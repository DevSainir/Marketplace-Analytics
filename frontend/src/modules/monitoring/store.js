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
import {
  fetchSkuDetail,
  fetchSkuSummary,
  getRefreshStatus,
  lookupSkus,
  previewMatrixEdit,
  refreshSku,
  saveMatrix,
} from '@/modules/monitoring/api'
import { buildMetricsMatrix, patchMetricsMatrix } from '@/modules/monitoring/metricsMatrix'

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

  // --- matrix editing state ---------------------------------------------
  /**
   * The display matrix ({days, rows}) the table renders. Kept as a STABLE
   * reactive object across edits: an edit/undo/redo patches only the changed
   * cells in place (see `patchMetricsMatrix`) instead of rebuilding it, so Vue
   * updates a handful of DOM nodes rather than re-rendering the whole table.
   */
  const matrixView = ref({ days: [], rows: [] })
  // The current editable working copy + its display matrix. Held as plain refs
  // (not the reactive table) so swapping them is cheap; snapshots reference
  // these immutable server payloads directly (no deep clone needed).
  const workingBase = ref(null)
  let currentMatrix = null
  // Undo/redo stacks of {base, matrix} states. Undo pops to the previous state;
  // redo (Ctrl+Shift+Z / Ctrl+Y) replays; a fresh edit clears the redo stack.
  const undoStack = ref([])
  const redoStack = ref([])

  /** True once the table has unsaved manual edits (enables «Сохранить»). */
  const matrixDirty = ref(false)
  /** A save (PUT) is in flight. */
  const matrixSaving = ref(false)
  /** A WB re-harvest («Обновить») is in flight (enqueue + poll). */
  const matrixRefreshing = ref(false)
  /** Transient message when an edit/save/refresh fails (e.g. a read-only cell). */
  const matrixEditError = ref(null)

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
      loadMatrix(detail)
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

  // --- matrix editing ----------------------------------------------------
  /** True when there is a value change to undo / redo. */
  const canUndoMatrix = computed(() => undoStack.value.length > 0)
  const canRedoMatrix = computed(() => redoStack.value.length > 0)

  /** Load a detail response: seed the product, working copy, and display view. */
  function loadMatrix(detail) {
    currentProduct.value = detail
    workingBase.value = detail.matrix_base
    currentMatrix = detail.matrix
    // Same window (save / refresh) → patch the existing table in place so only
    // changed cells re-render; a new SKU or window → rebuild from scratch.
    const days = matrixView.value.days
    const sameWindow =
      days.length > 0 &&
      days.length === (detail.matrix?.days?.length ?? 0) &&
      days.every((day, index) => day.iso === detail.matrix.days[index])
    if (!(sameWindow && patchMetricsMatrix(matrixView.value, detail))) {
      matrixView.value = buildMetricsMatrix(detail)
    }
    undoStack.value = []
    redoStack.value = []
    matrixDirty.value = false
    matrixEditError.value = null
  }

  /** Drop all edit/undo state (used by reset()). */
  function clearMatrixEditState() {
    workingBase.value = null
    currentMatrix = null
    matrixView.value = { days: [], rows: [] }
    undoStack.value = []
    redoStack.value = []
    matrixDirty.value = false
    matrixEditError.value = null
  }

  /**
   * Move to a new {base, matrix} state: swap the working copy and patch only
   * the changed cells into the live table (no full re-render).
   */
  function applyMatrixState(state) {
    workingBase.value = state.base
    currentMatrix = state.matrix
    // Patch in place; rebuild only if the shape somehow changed (window shift).
    if (!patchMetricsMatrix(matrixView.value, { matrix: state.matrix })) {
      matrixView.value = buildMetricsMatrix({ matrix: state.matrix })
    }
  }

  /**
   * Apply one cell edit: recompute dependents on the backend (nothing saved),
   * patch the table, and push the prior state onto the undo stack.
   *
   * @param {{day: string, bucket: string, metric: string, value: number}} edit
   */
  async function applyCellEdit(edit) {
    const product = currentProduct.value
    if (!product || !workingBase.value || matrixSaving.value || matrixRefreshing.value) return
    matrixEditError.value = null
    try {
      const result = await previewMatrixEdit(product.nm_id, workingBase.value, edit)
      undoStack.value.push({ base: workingBase.value, matrix: currentMatrix })
      redoStack.value = [] // a fresh edit invalidates the redo history
      applyMatrixState({ base: result.base, matrix: result.matrix })
      matrixDirty.value = true
    } catch (err) {
      // A read-only / non-invertible cell (422) or a network error: leave the
      // table untouched and surface a transient message.
      matrixEditError.value = extractErrorMessage(err)
    }
  }

  /** Undo the last value change (Ctrl+Z). */
  function undoMatrixEdit() {
    if (!undoStack.value.length) return
    redoStack.value.push({ base: workingBase.value, matrix: currentMatrix })
    applyMatrixState(undoStack.value.pop())
    matrixDirty.value = undoStack.value.length > 0
    matrixEditError.value = null
  }

  /** Redo a previously undone change (Ctrl+Shift+Z / Ctrl+Y). */
  function redoMatrixEdit() {
    if (!redoStack.value.length) return
    undoStack.value.push({ base: workingBase.value, matrix: currentMatrix })
    applyMatrixState(redoStack.value.pop())
    matrixDirty.value = true
    matrixEditError.value = null
  }

  /** Persist the current edits as overrides; refresh from the save response. */
  async function saveMatrixEdits() {
    const product = currentProduct.value
    if (!product || !matrixDirty.value || matrixSaving.value) return
    matrixSaving.value = true
    matrixEditError.value = null
    try {
      const params = product.window
        ? { date_from: product.window.start, date_to: product.window.end }
        : {}
      const detail = await saveMatrix(product.nm_id, workingBase.value, params)
      loadMatrix(detail)
    } catch (err) {
      matrixEditError.value = extractErrorMessage(err)
    } finally {
      matrixSaving.value = false
    }
  }

  /**
   * «Обновить»: re-harvest this SKU from WB (discarding manual edits), poll the
   * task to completion, then re-fetch the detail so the table shows fresh data.
   */
  async function refreshFromWb() {
    const product = currentProduct.value
    if (!product || matrixRefreshing.value) return
    const nmId = product.nm_id
    const params = product.window
      ? { date_from: product.window.start, date_to: product.window.end }
      : {}
    matrixRefreshing.value = true
    matrixEditError.value = null
    try {
      const { task_id: taskId } = await refreshSku(nmId)
      // Poll at a snappy interval so completion is noticed promptly (the harvest
      // itself is only a few seconds); keep a generous ~2 min ceiling in case
      // WB's advertising limiter throttles.
      const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms))
      for (let attempt = 0; attempt < 200; attempt += 1) {
        const status = await getRefreshStatus(taskId)
        if (status.ready) {
          if (!status.successful) throw new Error('Не удалось обновить данные из Wildberries.')
          break
        }
        await wait(600)
      }
      await fetchProductData(nmId, params)
    } catch (err) {
      matrixEditError.value = extractErrorMessage(err)
    } finally {
      matrixRefreshing.value = false
    }
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
    clearMatrixEditState()
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
    // matrix editing
    matrixView,
    matrixDirty,
    matrixSaving,
    matrixRefreshing,
    matrixEditError,
    canUndoMatrix,
    canRedoMatrix,
    applyCellEdit,
    undoMatrixEdit,
    redoMatrixEdit,
    saveMatrixEdits,
    refreshFromWb,
  }
})
