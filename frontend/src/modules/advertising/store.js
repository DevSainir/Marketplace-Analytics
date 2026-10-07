/**
 * «Реклама» Pinia store (setup style).
 *
 * The window is the only thing that costs a round trip. The bonus switch, the
 * table's grain, its filters and its search are all answered from the payload.
 *
 * The bonus switch is the кабинет's setting, stored on the server and shared by
 * everyone in it. A seller either has WB's promo bonuses or does not, so the
 * choice is made once — not per browser, where it had to be made again on every
 * device and by every manager.
 */
import { defineStore } from 'pinia'
import { computed, reactive, ref } from 'vue'

import { extractErrorMessage } from '@/core/api/axios'
import { presetWindow } from '@/core/utils/calendarModel'
import { isoDaysAgo } from '@/core/utils/dates'
import { recallPeriod, rememberPeriod } from '@/core/utils/periodMemory'
import { fetchAdvertising, fetchAdvertisingSpan } from '@/modules/advertising/api'
import { bidCards } from '@/modules/advertising/zoneModel'
import { useMembersStore, useWorkspaceStore } from '@/modules/profile'

/** Default window: thirty days, the span an advertising budget is reviewed over. */
const DEFAULT_DAYS = 30

/**
 * Longest window the page answers for, both ends counted — the backend's
 * `MAX_WINDOW_DAYS` (1200 days between the ends), so the calendar can grey out
 * what the API would refuse.
 */
export const MAX_PERIOD_DAYS = 1201

/** This page's key in `periodMemory`. */
const PERIOD_PAGE = 'advertising'

export const useAdvertisingStore = defineStore('advertising', () => {
  // Statistics are a stream that reaches today, so «the latest window» ends
  // today and the page need not wait for the span to know where that is.
  const periodEdge = () => ({ from: span.value?.date_from, to: isoDaysAgo(0) })
  const initial =
    recallPeriod(PERIOD_PAGE, { to: isoDaysAgo(0) }) ??
    presetWindow(DEFAULT_DAYS, { end: isoDaysAgo(0) })
  const dateFrom = ref(initial.from)
  const dateTo = ref(initial.to)

  const span = ref(null)
  const data = ref(null)
  const loading = ref(false)
  const error = ref('')
  let inFlight = null

  const workspaces = useWorkspaceStore()
  const members = useMembersStore()
  /** The кабинет's switch; on until someone in the кабинет turns it off. */
  const showBonus = computed(() => workspaces.currentWorkspace?.ads_show_bonus ?? true)
  /**
   * Who may not change it: a read-only manager, and a head looking into another
   * company's кабинет — the server refuses both, so the switch says so first.
   */
  const bonusLocked = computed(
    () => !members.canWrite || Boolean(workspaces.currentWorkspace?.is_guest),
  )
  const group = ref('sku')
  const filters = reactive({ query: '', subject: '', brand: '' })

  const currency = computed(() => data.value?.currency ?? '')
  const totals = computed(() => data.value?.totals ?? null)
  /** Whether the window carries any WB-funded spend at all. */
  const hasBonus = computed(() => Number(totals.value?.bonus ?? 0) > 0)
  /** What every bonus element on the page obeys: the switch, and the data. */
  const bonusVisible = computed(() => showBonus.value && hasBonus.value)
  /**
   * ДРР divides ad spend by settled sales. When the spend was billed in a
   * currency other than the settlement's, that is two units — withheld.
   */
  const drrComparable = computed(() =>
    (data.value?.ad_currencies ?? []).every((code) => code === currency.value),
  )
  /** The «Куда ушли деньги» cards, and the spend no card can hold. */
  const bids = computed(() => bidCards(data.value?.zones ?? []))

  async function load() {
    inFlight?.abort()
    const controller = new AbortController()
    inFlight = controller
    loading.value = true
    error.value = ''
    try {
      data.value = await fetchAdvertising(
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
   * Open on the last thirty days, and learn the advertising span ALONGSIDE.
   *
   * The two used to run one after the other — the span first, so the window
   * could end on its last day — which put a whole round trip in front of the
   * first figure. Advertising statistics are a stream that reaches today, so
   * the window can end today without waiting to be told; the span arrives in
   * parallel and only feeds the picker («Вся история» starts at its first
   * day). A failed span read is swallowed: the page does not need it to load.
   */
  async function init() {
    const spanRead = fetchAdvertisingSpan()
      .then((value) => {
        span.value = value
      })
      .catch(() => {
        span.value = null
      })
    await Promise.all([spanRead, load()])
  }

  /** Move the window, remember it for an hour, and reload. */
  function setPeriod(from, to) {
    if (from === dateFrom.value && to === dateTo.value) return
    dateFrom.value = from
    dateTo.value = to
    rememberPeriod(PERIOD_PAGE, from, to, periodEdge())
    return load()
  }

  /** Flip the кабинет's switch — for everyone in it, from now on. */
  function setShowBonus(on) {
    if (bonusLocked.value) return
    return workspaces.saveSettings({ ads_show_bonus: on })
  }

  function clearFilters() {
    filters.query = ''
    filters.subject = ''
    filters.brand = ''
  }

  return {
    dateFrom,
    dateTo,
    span,
    data,
    loading,
    error,
    showBonus,
    bonusLocked,
    group,
    filters,
    currency,
    totals,
    hasBonus,
    bonusVisible,
    drrComparable,
    bids,
    init,
    load,
    setPeriod,
    setShowBonus,
    clearFilters,
  }
})
