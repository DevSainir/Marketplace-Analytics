/**
 * Heatmap Pinia store (Composition-API setup style).
 *
 * What costs a request and what does not is the whole design. The window, the
 * metrics, the column width, the row cut and the three filters change what the
 * backend has to add up, so each of them reloads the grid. Sorting, paging and
 * the colour mode only rearrange rows the page already holds — the payload
 * carries every row of the selection — so they never touch the network.
 *
 * The default window is the thirty days ending YESTERDAY: today's funnel is
 * still filling, and a half-day painted red beside six whole ones reads as a
 * collapse that did not happen.
 */
import { defineStore } from 'pinia'
import { computed, ref, shallowRef, watch } from 'vue'

import { extractErrorMessage } from '@/core/api/axios'
import { presetWindow } from '@/core/utils/calendarModel'
import { daysBetween, isoDaysAgo } from '@/core/utils/dates'
import { recallPeriod, rememberPeriod } from '@/core/utils/periodMemory'
import * as api from '@/modules/heatmap/api'
import { pageOf, sortRows, tintRows } from '@/modules/heatmap/grid'
import { metricOf } from '@/modules/heatmap/metrics'
import { useHeatmapNormsStore } from '@/modules/heatmap/normsStore'
import { recallSettings, rememberSettings } from '@/modules/heatmap/settingsMemory'

/** The backend's own cap, repeated so the page can say it before asking. */
export const MAX_DAYS = 366

/** Default window: a month, ending yesterday. */
const DEFAULT_DAYS = 30

/** This page's key in `periodMemory`. */
const PERIOD_PAGE = 'heatmap'

export const useHeatmapStore = defineStore('heatmap', () => {
  const norms = useHeatmapNormsStore()
  // The period is remembered the way every page's is (`periodMemory`); the rest
  // of the page's choices through `settingsMemory`. «The latest window» here
  // ends yesterday — see the module comment.
  const periodEdge = () => ({ to: isoDaysAgo(1) })
  const initial =
    recallPeriod(PERIOD_PAGE, periodEdge()) ??
    presetWindow(DEFAULT_DAYS, { end: isoDaysAgo(1), maxDays: MAX_DAYS })
  const dateFrom = ref(initial.from)
  const dateTo = ref(initial.to)

  const metric = ref('orders')
  const metric2 = ref(null)
  const period = ref('day')
  const groupBy = ref('sku')
  const subjects = ref([])
  const groupIds = ref([])
  const nmIds = ref([])

  // --- answered from the payload -------------------------------------------
  const mode = ref('row')
  const sort = ref({ by: null, dir: 'desc' })
  const page = ref(1)
  const pageSize = ref(30)

  // Shallow: the payload is only ever replaced whole, never edited in place,
  // and a deep proxy over every row is work done on the page's own thread
  // exactly while it is busy taking the response in.
  const data = shallowRef(null)
  const loading = ref(false)
  const error = ref('')
  const catalog = ref({ items: [], subjects: [] })

  let inFlight = null

  // Settings that should survive a detour to another page or a reload — see
  // `settingsMemory.js`. Restored before any watcher exists, so a restore is
  // not itself a change.
  const REMEMBERED = {
    metric,
    metric2,
    period,
    groupBy,
    subjects,
    groupIds,
    nmIds,
    mode,
    sort,
    pageSize,
  }
  const recalled = recallSettings()
  if (recalled) {
    for (const [name, target] of Object.entries(REMEMBERED)) {
      if (name in recalled) target.value = recalled[name]
    }
    if (recalled.normMode) norms.mode = recalled.normMode
  }
  watch(
    [...Object.values(REMEMBERED), () => norms.mode],
    () => {
      const settings = Object.fromEntries(
        Object.entries(REMEMBERED).map(([name, target]) => [name, target.value]),
      )
      rememberSettings({ ...settings, normMode: norms.mode })
    },
    { deep: true },
  )

  const primary = computed(() => metricOf(data.value?.metric ?? metric.value))
  const secondary = computed(() => metricOf(data.value?.metric2 ?? null))
  const columns = computed(() => data.value?.columns ?? [])
  const totals = computed(() => data.value?.totals ?? null)
  const sortedRows = computed(() => sortRows(data.value?.rows ?? [], sort.value))
  const view = computed(() => pageOf(sortedRows.value, page.value, pageSize.value))
  /** Hand-set norms apply to articles only — a category has no norm of its own. */
  const manualNorms = computed(
    () => norms.mode === 'manual' && data.value?.group_by === 'sku' && primary.value !== null,
  )
  const tints = computed(() =>
    tintRows(
      view.value.rows,
      sortedRows.value,
      mode.value,
      primary.value ?? { key: 'orders', direction: 'up' },
      manualNorms.value
        ? {
            columns: columns.value,
            normOf: (row) => norms.normOf(row.nm_id, primary.value.key),
          }
        : {},
    ),
  )
  const tooLong = computed(() => daysBetween(dateFrom.value, dateTo.value) + 1 > MAX_DAYS)

  /** Everything that changes what the backend adds up, as one watchable value. */
  const request = computed(() => ({
    date_from: dateFrom.value,
    date_to: dateTo.value,
    metric: metric.value,
    ...(metric2.value ? { metric2: metric2.value } : {}),
    period: period.value,
    group_by: groupBy.value,
    subjects: subjects.value,
    group_ids: groupIds.value,
    nm_ids: nmIds.value,
  }))

  async function load() {
    if (tooLong.value) {
      error.value = `Можно выбрать только период не длиннее ${MAX_DAYS} дней — выберите короче.`
      return
    }
    inFlight?.abort()
    const controller = new AbortController()
    inFlight = controller
    loading.value = true
    error.value = ''
    try {
      data.value = await api.fetchHeatmap(request.value, controller.signal)
    } catch (err) {
      if (controller.signal.aborted) return
      error.value = extractErrorMessage(err)
    } finally {
      if (inFlight === controller) {
        loading.value = false
        inFlight = null
      }
    }
  }

  /** The article pickers sort by orders in the period on screen, so they follow it. */
  async function loadCatalog() {
    catalog.value = await api.fetchCatalog({ date_from: dateFrom.value, date_to: dateTo.value })
  }

  async function init() {
    const side = loadCatalog().catch((err) => (error.value = extractErrorMessage(err)))
    await Promise.all([load(), side])
  }

  watch([dateFrom, dateTo], () => {
    if (!tooLong.value) loadCatalog().catch((err) => (error.value = extractErrorMessage(err)))
  })

  // A new question starts on page one; the sort survives, it is still meaningful.
  watch(request, () => {
    page.value = 1
    load()
  })

  // A different page size or order starts from the top again.
  watch([pageSize, sort], () => (page.value = 1))

  function setPeriod({ from, to }) {
    dateFrom.value = from
    dateTo.value = to
    rememberPeriod(PERIOD_PAGE, from, to, periodEdge())
  }

  /** ⇄ — the second metric becomes the painted one, and the first goes below it. */
  function swapMetrics() {
    if (!metric2.value) return
    ;[metric.value, metric2.value] = [metric2.value, metric.value]
  }

  /** Desc, then asc, then back to «популярность». */
  function toggleSort(by) {
    const current = sort.value
    if (current.by !== by) sort.value = { by, dir: 'desc' }
    else if (current.dir === 'desc') sort.value = { by, dir: 'asc' }
    else sort.value = { by: null, dir: 'desc' }
  }

  return {
    dateFrom,
    dateTo,
    metric,
    metric2,
    period,
    groupBy,
    subjects,
    groupIds,
    nmIds,
    mode,
    sort,
    page,
    pageSize,
    data,
    loading,
    error,
    catalog,
    primary,
    secondary,
    columns,
    totals,
    sortedRows,
    view,
    tints,
    manualNorms,
    tooLong,
    init,
    load,
    setPeriod,
    swapMetrics,
    toggleSort,
  }
})
