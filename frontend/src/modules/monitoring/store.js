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
import { isoDaysAgo } from '@/core/utils/dates'
import {
  fetchPinnedSkus,
  fetchSkuDetail,
  fetchAggregateCharts,
  fetchSkuSummary,
  fetchStockDay,
  getRefreshStatus,
  lookupSkus,
  previewMatrixEdit,
  refreshAllSkus,
  refreshSku,
  reorderPinnedSkus,
  saveMatrix,
  setDayAction,
  setDayComment,
  setSkuPin,
  setSkuPinColor,
  setWarehouseMark,
} from '@/modules/monitoring/api'
import { buildMetricsMatrix, patchMetricsMatrix } from '@/modules/monitoring/metricsMatrix'

/** Poll interval while waiting for a «Обновить» harvest task, in ms. */
const REFRESH_POLL_INTERVAL_MS = 600

/**
 * How long to keep polling a «Обновить» harvest before calling it failed.
 *
 * This is a CEILING ON THE BACKEND'S WORST CASE, not a guess at a comfortable
 * wait, and it is why the number looks large. It must stay ABOVE the task's own
 * soft time limit (25 min, `_INTERACTIVE_SOFT_TIME_LIMIT_SECONDS` in
 * `backend/src/modules/monitoring/tasks/refresh.py`), so the task is killed and
 * reports failure before the poller gives up guessing.
 *
 * The worst case grew when «Обновить» stopped being a subset of the nightly
 * pass: it now pulls the account-wide sale feed and the 22-day buyout-cohort
 * pass, and the cohort pass alone is 22 sequential rate-limited requests
 * measuring ~7 minutes. The common case is far shorter — the cohort pass is
 * claimed per workspace for an hour, so only the first refresh in that window
 * pays for it.
 *
 * The old ceiling was 120s — BELOW the worst case of the day. On 2026-07-30
 * harvests that genuinely succeeded in 144-198s were all reported to the user
 * as "не завершилось за отведённое время", which is why «Обновить» appeared
 * never to work. A ceiling under the backend's own limit turns every slow
 * success into a visible failure.
 */
const REFRESH_POLL_CEILING_MS = 30 * 60 * 1000

/**
 * Ceiling for the bulk «Обновить все SKU» harvest, which covers the whole
 * catalogue in one task — and, on a workspace with no catalogue yet, discovers
 * it from the Content API first.
 *
 * The same value as the single-SKU ceiling rather than a multiple of it. The
 * two now run the identical body (`refresh_workspace_data`), and the expensive
 * parts of it — the account-wide sale feed and the buyout-cohort pass — cost
 * the same whether one SKU or the whole catalogue is being refreshed. What
 * scales with SKU count is the funnel, fetched in chunks of 20 nmIDs, so a
 * 50-SKU account is a handful of extra analytics calls, not 50×. (Locally,
 * under WB_FAKE_HARVEST, it returns in well under a second.)
 */
const REFRESH_ALL_POLL_CEILING_MS = 30 * 60 * 1000

/**
 * Interval the poll relaxes to after the first few seconds. The harvest is
 * usually quick, so the first seconds are polled tightly; a refresh queueing
 * behind WB's rate budget does not need 600ms resolution for minutes on end.
 */
const REFRESH_POLL_SLOW_INTERVAL_MS = 2000

/** When to switch from the tight interval to the relaxed one, in ms. */
const REFRESH_POLL_RELAX_AFTER_MS = 10 * 1000

/**
 * WB source labels as the backend names them, in the words the table uses.
 * An unmapped label falls back to itself rather than being dropped — a source
 * we forgot to translate must still be reported.
 */
const WB_SOURCE_LABELS = {
  'sales-funnel': 'воронку продаж',
  stocks: 'остатки',
  campaigns: 'кампании',
  'adverts-v2': 'настройки кампаний',
  advertising: 'статистику рекламы',
  'search-zone': 'поисковую зону',
  prices: 'цены',
  'card-prices': 'цены покупателя',
  sales: 'выкупы и возвраты',
}

/** Translate one backend WB source label for display. */
function sourceLabel(source) {
  return WB_SOURCE_LABELS[source] ?? source
}

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

  // --- account-wide charts («Сравнение SKU») -----------------------------------
  /** The aggregate display matrix the «Сравнение SKU» page draws, or an empty one. */
  const aggregateView = ref({
    days: [],
    rows: [],
    priceRows: [],
    stockRows: [],
    stockTotalRows: [],
  })
  const aggregateLoading = ref(false)
  const aggregateError = ref(null)
  /** How many SKUs actually contributed a day — the page states its own scope. */
  const aggregateSkuCount = ref(0)

  // --- matrix editing state ---------------------------------------------
  /**
   * The display matrix ({days, rows}) the table renders. Kept as a STABLE
   * reactive object across edits: an edit/undo/redo patches only the changed
   * cells in place (see `patchMetricsMatrix`) instead of rebuilding it, so Vue
   * updates a handful of DOM nodes rather than re-rendering the whole table.
   */
  const matrixView = ref({ days: [], rows: [], priceRows: [], stockRows: [], stockTotalRows: [] })
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
  /**
   * How far the in-flight «Обновить» has got: `{ percent, message }`, or null
   * when nothing is running.
   *
   * A first refresh can run ~8 minutes — it includes the account-wide sale feed
   * and the 22-day buyout-cohort pass — and eight silent minutes behind a
   * disabled button reads as a hung request. The message is the backend's own
   * Russian line, not one assembled here, so the stages can change without the
   * two descriptions drifting apart.
   */
  const refreshProgress = ref(null)
  /**
   * Transient message for ANY failed user action on the detail page, not just
   * matrix edits: a rejected cell edit (422 on a read-only cell), a failed
   * save/refresh, and every optimistic toggle that had to roll back — pins,
   * chip reorder and colour, warehouse marks, day notes, «Действия», and the
   * two stock-comparison sides. One sink because they all surface in the same
   * place under the table.
   */
  const actionError = ref(null)
  /**
   * A completed-but-incomplete action: the refresh ran, WB withheld some of its
   * sources, so part of the table is deliberately unchanged. Separate from
   * `actionError` because nothing failed on our side and there is nothing to
   * retry right now — it explains, it does not alarm.
   */
  const actionWarning = ref(null)

  /** A bulk «Обновить все SKU» harvest is in flight (enqueue + poll). */
  const allRefreshing = ref(false)
  /** How far the in-flight bulk refresh has got; see {@link refreshProgress}. */
  const allRefreshProgress = ref(null)
  /**
   * Error/partial-outcome messages for the BULK refresh, kept separate from
   * `actionError`/`actionWarning`: the bulk button lives beside the period
   * picker and is visible with no SKU open, so its messages must not surface
   * under the metrics table (and vice versa).
   */
  const allRefreshError = ref(null)
  const allRefreshWarning = ref(null)

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

  // --- pinned SKUs ---------------------------------------------------------
  // The GLOBAL pinned list («Закрепить»): shared by every account, rendered as
  // the chip row under the search bar. A toggle applies optimistically and then
  // reconciles with the server's full list (or rolls back on failure).
  const pinnedSkus = ref([])

  /** Whether one SKU is currently pinned. */
  const pinnedIds = computed(() => new Set(pinnedSkus.value.map((item) => item.nm_id)))

  /** Load the global pinned-SKU chip row (once on mount; toggles keep it fresh). */
  async function fetchPins() {
    try {
      pinnedSkus.value = (await fetchPinnedSkus()).items
    } catch {
      // The chip row is decoration — a failed load must not block the page.
      pinnedSkus.value = []
    }
  }

  /** Pin an unpinned SKU («Закрепить») or unpin a pinned one («Закреплено»). */
  async function toggleSkuPin(nmId, label = null) {
    const previous = pinnedSkus.value
    const pinned = !pinnedIds.value.has(nmId)
    pinnedSkus.value = pinned
      ? [...previous, { nm_id: nmId, vendor_code: label, title: null, color: null }]
      : previous.filter((item) => item.nm_id !== nmId)
    try {
      const result = await setSkuPin(nmId, pinned)
      pinnedSkus.value = result.items
    } catch (err) {
      pinnedSkus.value = previous
      actionError.value = extractErrorMessage(err)
    }
  }

  /** Persist the chip row's order after a drag-and-drop (shared by everyone). */
  async function reorderPins(nmIds) {
    const previous = pinnedSkus.value
    const byId = new Map(previous.map((item) => [item.nm_id, item]))
    pinnedSkus.value = nmIds.map((nmId) => byId.get(nmId)).filter(Boolean)
    try {
      const result = await reorderPinnedSkus(nmIds)
      pinnedSkus.value = result.items
    } catch (err) {
      // The backend rejects an order computed against a list a teammate has
      // since changed — the rollback puts the real one back on screen.
      pinnedSkus.value = previous
      actionError.value = extractErrorMessage(err)
    }
  }

  /** Paint a pinned chip's background, or clear its tint (color = null). */
  async function setPinColor(nmId, color) {
    const previous = pinnedSkus.value
    pinnedSkus.value = previous.map((item) => (item.nm_id === nmId ? { ...item, color } : item))
    try {
      const result = await setSkuPinColor(nmId, color)
      pinnedSkus.value = result.items
    } catch (err) {
      pinnedSkus.value = previous
      actionError.value = extractErrorMessage(err)
    }
  }

  // --- two-day stock comparison --------------------------------------------
  // The «Остатки по складам» section shows TWO snapshot days side by side for
  // visual dynamics: right = today, left = yesterday by default; each side has
  // its own day picker. Sides are fetched independently per picked day.
  const stockCompare = ref({
    left: { date: isoDaysAgo(1), loading: false, stock: null },
    right: { date: isoDaysAgo(0), loading: false, stock: null },
  })

  /** Fetch one side's snapshot; optionally repointing it to a new day first. */
  async function fetchStockCompareSide(side, newDate = null) {
    const nmId = currentProduct.value?.nm_id
    if (!nmId) return
    const entry = stockCompare.value[side]
    if (newDate) entry.date = newDate
    entry.loading = true
    try {
      const result = await fetchStockDay(nmId, entry.date)
      // Apply only while the same SKU is displayed (SKU-switch race guard).
      if (currentProduct.value?.nm_id === nmId) entry.stock = result.stock
    } catch (err) {
      if (currentProduct.value?.nm_id === nmId) {
        entry.stock = null
        actionError.value = extractErrorMessage(err)
      }
    } finally {
      entry.loading = false
    }
  }

  /** (Re)load both comparison sides for the current SKU. */
  function fetchStockCompare() {
    return Promise.all([fetchStockCompareSide('left'), fetchStockCompareSide('right')])
  }

  // --- warehouse marks -----------------------------------------------------
  // Warehouses «на отгрузку» for the CURRENT SKU: persisted on the backend
  // (monitoring.warehouse_mark), scoped per nm_id — marking «Тула» on one SKU
  // says nothing about «Тула» on another. Seeded from the detail response
  // (`stock.marked_warehouses`); a toggle applies optimistically and then
  // reconciles with the server's answer (or rolls back on failure).
  const markedWarehouses = ref([])

  /** Mark an unmarked warehouse («Отгрузить») or unmark a marked one («Разгрузить»). */
  async function toggleWarehouseMark(name) {
    const nmId = currentProduct.value?.nm_id
    if (!nmId) return
    const previous = markedWarehouses.value
    const marked = !previous.includes(name)
    markedWarehouses.value = marked
      ? [...previous, name]
      : previous.filter((warehouse) => warehouse !== name)
    try {
      const result = await setWarehouseMark(nmId, name, marked)
      // Reconcile only while the same SKU is displayed (guards the race with
      // a SKU switch while the request was in flight).
      if (currentProduct.value?.nm_id === nmId) {
        markedWarehouses.value = result.marked_warehouses
      }
    } catch (err) {
      if (currentProduct.value?.nm_id === nmId) markedWarehouses.value = previous
      actionError.value = extractErrorMessage(err)
    }
  }

  // --- day notes («Комментарий» + its header) --------------------------------
  // Per-day notes on the CURRENT SKU: persisted on the backend
  // (monitoring.sku_day_comment), global per (nm_id, day) — shared by every
  // account. The persisted map rides on `currentProduct.comments` (keyed by ISO
  // day, `{body, header}`); the table owns the drafts.
  //
  // Both fields are plain per-day facts here. The header's continuation onto a
  // new day happens ONCE at the day boundary, server-side, and arrives as a
  // stored row — the frontend never derives it, so editing one day's header
  // leaves every other day alone.
  /** ISO days with a save (PUT) in flight — the row disables just those inputs. */
  const commentSavingDays = ref(new Set())

  /**
   * Persist one field of a day's note (blanking both clears the day).
   *
   * @param {string} iso The day, as YYYY-MM-DD.
   * @param {{body?: string, header?: string}} patch The field just edited.
   */
  async function saveDayComment(iso, patch) {
    const nmId = currentProduct.value?.nm_id
    if (!nmId || commentSavingDays.value.has(iso)) return
    // A new Set per mutation: Vue tracks the ref's value, not the Set's writes.
    commentSavingDays.value = new Set(commentSavingDays.value).add(iso)
    actionError.value = null
    try {
      const result = await setDayComment(nmId, iso, patch)
      // Apply only while the same SKU is displayed (SKU-switch race guard).
      if (currentProduct.value?.nm_id !== nmId) return
      const comments = { ...(currentProduct.value.comments ?? {}) }
      if (result.note == null) {
        delete comments[iso]
      } else {
        comments[iso] = result.note
      }
      currentProduct.value.comments = comments
    } catch (err) {
      actionError.value = extractErrorMessage(err)
    } finally {
      const pending = new Set(commentSavingDays.value)
      pending.delete(iso)
      commentSavingDays.value = pending
    }
  }

  // --- day actions («Действия»: РК toggles + budgets, price change) ---------
  // Per-day answered questions under the comments row: persisted on the backend
  // (monitoring.sku_day_action), global per (nm_id, day). The persisted map
  // rides on `currentProduct.day_actions` (keyed by ISO day, touched days
  // only); each change PUTs the merged FULL day state (last write wins).
  /** ISO days with an action save (PUT) in flight — their controls disable. */
  const actionSavingDays = ref(new Set())

  /** Merge one day's partial change into its stored state and persist it. */
  async function saveDayAction(iso, patch) {
    const nmId = currentProduct.value?.nm_id
    if (!nmId || actionSavingDays.value.has(iso)) return
    const next = { ...(currentProduct.value.day_actions?.[iso] ?? {}), ...patch }
    // A new Set per mutation: Vue tracks the ref's value, not the Set's writes.
    actionSavingDays.value = new Set(actionSavingDays.value).add(iso)
    actionError.value = null
    try {
      const result = await setDayAction(nmId, iso, next)
      // Apply only while the same SKU is displayed (SKU-switch race guard).
      if (currentProduct.value?.nm_id !== nmId) return
      const actions = { ...(currentProduct.value.day_actions ?? {}) }
      if (result.action == null) {
        delete actions[iso]
      } else {
        actions[iso] = result.action
      }
      currentProduct.value.day_actions = actions
    } catch (err) {
      actionError.value = extractErrorMessage(err)
    } finally {
      const pending = new Set(actionSavingDays.value)
      pending.delete(iso)
      actionSavingDays.value = pending
    }
  }

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
  let aggregateController = null

  /**
   * Load the account-wide day series for «Сравнение SKU».
   *
   * An empty `nmIds` means every SKU in the workspace — the page's default.
   * The response is a matrix in the SAME shape the per-SKU detail serves, so it
   * goes through `buildMetricsMatrix` unchanged and the charts cannot end up
   * reading the two pages differently.
   *
   * @param {{date_from?: string, date_to?: string, nmIds?: number[]}} [params]
   */
  async function fetchAggregate(params = {}) {
    aggregateController?.abort()
    const controller = new AbortController()
    aggregateController = controller

    aggregateLoading.value = true
    aggregateError.value = null
    try {
      const result = await fetchAggregateCharts(params, controller.signal)
      aggregateView.value = buildMetricsMatrix(result)
      aggregateSkuCount.value = result.sku_count ?? 0
    } catch (err) {
      if (isAbortError(err)) return
      aggregateView.value = { days: [], rows: [], priceRows: [], stockRows: [], stockTotalRows: [] }
      aggregateSkuCount.value = 0
      aggregateError.value = extractErrorMessage(err)
    } finally {
      if (aggregateController === controller) {
        aggregateLoading.value = false
        aggregateController = null
      }
    }
  }

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
    markedWarehouses.value = detail.stock?.marked_warehouses ?? []
    fetchStockCompare()
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
    actionError.value = null
  }

  /** Drop all edit/undo state (used by reset()). */
  function clearMatrixEditState() {
    workingBase.value = null
    currentMatrix = null
    matrixView.value = { days: [], rows: [], priceRows: [], stockRows: [], stockTotalRows: [] }
    undoStack.value = []
    redoStack.value = []
    matrixDirty.value = false
    actionError.value = null
    actionWarning.value = null
  }

  /**
   * Move to a new {base, matrix} state: swap the working copy and patch only
   * the changed cells into the live table (no full re-render).
   */
  function applyMatrixState(state) {
    workingBase.value = state.base
    currentMatrix = state.matrix
    // The per-variant breakdown behind the carts/orders hover rides on the
    // BASE, so the new base has to travel with the matrix — patching with the
    // matrix alone rebuilds every cell's `assoc` with an empty variant list and
    // guts the menu after each edit/undo/redo.
    const next = {
      matrix: state.matrix,
      matrix_base: state.base,
      nm_id: currentProduct.value?.nm_id,
    }
    // Patch in place; rebuild only if the shape somehow changed (window shift).
    if (!patchMetricsMatrix(matrixView.value, next)) {
      matrixView.value = buildMetricsMatrix(next)
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
    actionError.value = null
    try {
      const result = await previewMatrixEdit(product.nm_id, workingBase.value, edit)
      undoStack.value.push({ base: workingBase.value, matrix: currentMatrix })
      redoStack.value = [] // a fresh edit invalidates the redo history
      applyMatrixState({ base: result.base, matrix: result.matrix })
      matrixDirty.value = true
    } catch (err) {
      // A read-only / non-invertible cell (422) or a network error: leave the
      // table untouched and surface a transient message.
      actionError.value = extractErrorMessage(err)
    }
  }

  /** Undo the last value change (Ctrl+Z). */
  function undoMatrixEdit() {
    if (!undoStack.value.length) return
    redoStack.value.push({ base: workingBase.value, matrix: currentMatrix })
    applyMatrixState(undoStack.value.pop())
    matrixDirty.value = undoStack.value.length > 0
    actionError.value = null
  }

  /** Redo a previously undone change (Ctrl+Shift+Z / Ctrl+Y). */
  function redoMatrixEdit() {
    if (!redoStack.value.length) return
    undoStack.value.push({ base: workingBase.value, matrix: currentMatrix })
    applyMatrixState(redoStack.value.pop())
    matrixDirty.value = true
    actionError.value = null
  }

  /** Persist the current edits as overrides; refresh from the save response. */
  async function saveMatrixEdits() {
    const product = currentProduct.value
    if (!product || !matrixDirty.value || matrixSaving.value) return
    matrixSaving.value = true
    actionError.value = null
    try {
      const params = product.window
        ? { date_from: product.window.start, date_to: product.window.end }
        : {}
      const detail = await saveMatrix(product.nm_id, workingBase.value, params)
      loadMatrix(detail)
    } catch (err) {
      actionError.value = extractErrorMessage(err)
    } finally {
      matrixSaving.value = false
    }
  }

  /**
   * Poll one refresh task to completion, surfacing its staged progress.
   *
   * Shared by «Обновить» and «Обновить все SKU», which differ only in what they
   * redraw and which ceiling they use. It was duplicated once and the two
   * copies had already drifted on how they reported a partial outcome.
   *
   * `onStageComplete` is the interesting part. The backend runs a refresh in
   * two stages and COMMITS the first before starting the second, so when the
   * reported stage advances, the previous stage's rows are durable — the caller
   * can put advertising and funnel data on screen while buyout percentages are
   * still being counted, instead of making the seller wait out the slow half
   * to see the fast half.
   *
   * @param {string} taskId
   * @param {number} ceilingMs Give up after this; see REFRESH_POLL_CEILING_MS.
   * @param {{onProgress: Function, onStageComplete: Function}} handlers
   * @returns {Promise<string[]|null>} Withheld WB sources, or null on timeout.
   */
  async function pollRefreshTask(taskId, ceilingMs, { onProgress, onStageComplete }) {
    const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms))
    const startedAt = Date.now()
    let lastStage = 0
    while (Date.now() - startedAt < ceilingMs) {
      const status = await getRefreshStatus(taskId)
      if (typeof status.percent === 'number' || status.message) {
        onProgress({ percent: status.percent ?? null, message: status.message ?? '' })
      }
      if (typeof status.stage === 'number' && status.stage > lastStage) {
        // Redraw with what the FINISHED stage wrote, never the one now running.
        if (lastStage > 0) await onStageComplete(lastStage)
        lastStage = status.stage
      }
      if (status.ready) {
        if (!status.successful) throw new Error('Не удалось обновить данные из Wildberries.')
        return status.failed_sources ?? []
      }
      const elapsed = Date.now() - startedAt
      await wait(
        elapsed < REFRESH_POLL_RELAX_AFTER_MS
          ? REFRESH_POLL_INTERVAL_MS
          : REFRESH_POLL_SLOW_INTERVAL_MS,
      )
    }
    return null
  }

  /**
   * «Обновить»: re-harvest this SKU from WB (discarding manual edits), poll the
   * task to completion, then re-fetch the detail so the table shows fresh data.
   *
   * The table is redrawn TWICE on a full run: once when the advertising/funnel
   * stage commits, and again at the end when buyout percentages land.
   */
  async function refreshFromWb() {
    const product = currentProduct.value
    if (!product || matrixRefreshing.value) return
    const nmId = product.nm_id
    const params = product.window
      ? { date_from: product.window.start, date_to: product.window.end }
      : {}
    matrixRefreshing.value = true
    refreshProgress.value = null
    actionError.value = null
    actionWarning.value = null
    try {
      const { task_id: taskId } = await refreshSku(nmId)
      // Poll tightly at first (the harvest is usually seconds), then relax —
      // and keep going until the backend's own worst case has elapsed, never
      // less. See REFRESH_POLL_CEILING_MS.
      const failedSources = await pollRefreshTask(taskId, REFRESH_POLL_CEILING_MS, {
        onProgress: (progress) => {
          refreshProgress.value = progress
        },
        // Advertising, funnel, stocks and prices are committed by now. Putting
        // them on screen here is the whole point of staging the refresh: the
        // seller reads the numbers they came for while the ~7-minute buyout
        // pass is still running behind the bar.
        onStageComplete: () => fetchProductData(nmId, params),
      })
      // Exhausting the ceiling is a FAILURE, not a silent success: falling
      // through here would clear the spinner and re-fetch unchanged data,
      // presenting stale numbers as a completed refresh.
      if (failedSources === null) {
        throw new Error(
          'Обновление из Wildberries не завершилось за отведённое время. ' +
            'Данные могут обновиться позже — попробуйте ещё раз.',
        )
      }
      await fetchProductData(nmId, params)
      // A harvest tolerates a partial WB outage, so "successful" can still mean
      // the funnel never arrived and the table redraws its previous numbers.
      // Saying so is the difference between a working button and one the user
      // believes is broken.
      actionWarning.value = failedSources.length
        ? `Wildberries не отдал: ${failedSources.map(sourceLabel).join(', ')}. ` +
          'Эти данные остались прежними — попробуйте позже.'
        : null
    } catch (err) {
      actionError.value = extractErrorMessage(err)
    } finally {
      matrixRefreshing.value = false
      refreshProgress.value = null
    }
  }

  /**
   * «Обновить все SKU»: re-harvest the WHOLE workspace catalogue from WB (one
   * task over every SKU, discarding their manual edits), poll it to completion,
   * then refresh what's on screen — the SKU list always, and the open SKU's
   * detail if one is shown. Independent of {@link refreshFromWb}: it can run on
   * the empty/list view where no SKU is selected.
   */
  async function refreshAllFromWb() {
    if (allRefreshing.value) return
    allRefreshing.value = true
    allRefreshProgress.value = null
    allRefreshError.value = null
    allRefreshWarning.value = null
    try {
      const { task_id: taskId } = await refreshAllSkus()
      // Reflect the fresh data: the list always, and the open SKU if any.
      const redraw = async () => {
        await fetchSkuList(lastParams)
        if (currentProduct.value) {
          await fetchProductData(currentProduct.value.nm_id, lastParams)
        }
      }
      const failedSources = await pollRefreshTask(taskId, REFRESH_ALL_POLL_CEILING_MS, {
        onProgress: (progress) => {
          allRefreshProgress.value = progress
        },
        onStageComplete: redraw,
      })
      if (failedSources === null) {
        throw new Error(
          'Обновление всех SKU не завершилось за отведённое время. ' +
            'Данные могут обновиться позже — попробуйте ещё раз.',
        )
      }
      await redraw()
      allRefreshWarning.value = failedSources.length
        ? `Wildberries не отдал: ${failedSources.map(sourceLabel).join(', ')}. ` +
          'Эти данные остались прежними — попробуйте позже.'
        : null
    } catch (err) {
      allRefreshError.value = extractErrorMessage(err)
    } finally {
      allRefreshing.value = false
      allRefreshProgress.value = null
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
    markedWarehouses.value = []
    stockCompare.value = {
      left: { date: isoDaysAgo(1), loading: false, stock: null },
      right: { date: isoDaysAgo(0), loading: false, stock: null },
    }
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
    aggregateView,
    aggregateLoading,
    aggregateError,
    aggregateSkuCount,
    fetchAggregate,
    selectSku,
    totalCarts,
    totalAdClicks,
    totalOrders,
    totalAdSpend,
    isOutOfStock,
    pinnedSkus,
    pinnedIds,
    fetchPins,
    toggleSkuPin,
    reorderPins,
    setPinColor,
    markedWarehouses,
    toggleWarehouseMark,
    commentSavingDays,
    saveDayComment,
    actionSavingDays,
    saveDayAction,
    stockCompare,
    fetchStockCompareSide,
    fetchProductData,
    reset,
    // matrix editing
    matrixView,
    matrixDirty,
    matrixSaving,
    matrixRefreshing,
    refreshProgress,
    actionError,
    actionWarning,
    canUndoMatrix,
    canRedoMatrix,
    applyCellEdit,
    undoMatrixEdit,
    redoMatrixEdit,
    saveMatrixEdits,
    refreshFromWb,
    // bulk «Обновить все SKU»
    allRefreshing,
    allRefreshProgress,
    allRefreshError,
    allRefreshWarning,
    refreshAllFromWb,
  }
})
