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
import { computed, ref, watch } from 'vue'

import { extractErrorMessage } from '@/core/api/axios'
import { presetRange } from '@/core/utils/calendarModel'
import { daysBetween, isoDaysAgo } from '@/core/utils/dates'
import * as api from '@/modules/heatmap/api'
import { pageOf, sortRows, tintRows } from '@/modules/heatmap/grid'
import { metricOf } from '@/modules/heatmap/metrics'
import { useHeatmapNormsStore } from '@/modules/heatmap/normsStore'

/** The backend's own cap, repeated so the page can say it before asking. */
export const MAX_DAYS = 366

/** Default window: a month, ending yesterday. */
const DEFAULT_DAYS = 30

export const useHeatmapStore = defineStore('heatmap', () => {
  const norms = useHeatmapNormsStore()
  const initial = presetRange(DEFAULT_DAYS, isoDaysAgo(1))
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

  const data = ref(null)
  const loading = ref(false)
  const error = ref('')
  const catalog = ref({ items: [], subjects: [] })
  const groups = ref([])
  const groupBusy = ref(false)
  const groupError = ref('')

  let inFlight = null

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

  async function loadGroups() {
    groups.value = (await api.fetchGroups()).items
  }

  /** The article pickers sort by orders in the period on screen, so they follow it. */
  async function loadCatalog() {
    catalog.value = await api.fetchCatalog({ date_from: dateFrom.value, date_to: dateTo.value })
  }

  async function init() {
    const side = Promise.all([loadCatalog(), loadGroups(), norms.load()]).catch(
      (err) => (error.value = extractErrorMessage(err)),
    )
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

  /**
   * Create or edit a group, then refresh the list. A group the grid is filtered
   * or cut by changes the grid too, so that reloads as well.
   *
   * @param {{id?: string, name: string, nm_ids: number[]}} group
   * @returns {Promise<boolean>} Whether it saved.
   */
  async function saveGroup(group) {
    groupBusy.value = true
    groupError.value = ''
    try {
      const payload = { name: group.name, nm_ids: group.nm_ids }
      if (group.id) await api.updateGroup(group.id, payload)
      else await api.createGroup(payload)
      await loadGroups()
      if (groupBy.value === 'group' || groupIds.value.includes(group.id)) load()
      return true
    } catch (err) {
      groupError.value = extractErrorMessage(err)
      return false
    } finally {
      groupBusy.value = false
    }
  }

  /** @returns {Promise<boolean>} Whether it was deleted. */
  async function removeGroup(id) {
    groupBusy.value = true
    groupError.value = ''
    try {
      await api.deleteGroup(id)
      await loadGroups()
      if (groupIds.value.includes(id)) groupIds.value = groupIds.value.filter((g) => g !== id)
      else if (groupBy.value === 'group') load()
      return true
    } catch (err) {
      groupError.value = extractErrorMessage(err)
      return false
    } finally {
      groupBusy.value = false
    }
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
    groups,
    groupBusy,
    groupError,
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
    saveGroup,
    removeGroup,
  }
})
