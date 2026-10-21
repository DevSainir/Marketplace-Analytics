/**
 * Two-way sync between the monitoring page's search state and the URL.
 *
 * The URL is the single source of truth, deliberately: a SKU plus a window is
 * exactly what people paste to each other ("look at M-TRX01-BLK for last
 * week"), so the page has to restore fully from a link and every search has
 * to leave one behind. Back/forward then work for free — the watcher re-runs on
 * any query change, whoever caused it — and the handlers stay trivial, because
 * they only push a query and never fetch.
 *
 * That asymmetry is the rule worth keeping: HANDLERS PUSH, THE WATCHER FETCHES.
 * A handler that also fetched would double-fetch on its own navigation and
 * fetch nothing at all on Back.
 *
 * A URL with no window in it opens on the window this page was left on within
 * the hour (`periodMemory`, kept apart from every other page's), and only then
 * on the default — so leaving for the P&L and coming back by the menu does not
 * throw the chosen period away. A window in the URL always wins: a pasted link
 * means exactly the dates it names.
 *
 * Extracted from `MonitoringView` because routing is not what the page is
 * about, and because these ordering rules deserve a place of their own.
 */

/** This page's key in `periodMemory`. */
const PERIOD_PAGE = 'monitoring'

/** «The latest window» here ends today: the funnel and the snapshots are live. */
const periodEdge = () => ({ to: isoDaysAgo(0) })

/** Longest window the API answers for, both ends counted (its cap is days BETWEEN them). */
export const MAX_PERIOD_DAYS = MAX_WINDOW_DAYS + 1

/**
 * The window a URL without one opens on: the calendar's «30 дней» ending
 * today — the funnel has no current-day data yet (blank cells), but today's
 * price/stock snapshots must already show. Built by the preset itself, so the
 * page opens with that preset lit.
 */
const defaultWindow = () => presetWindow(30, { end: isoDaysAgo(0) })
import { ref, watch } from 'vue'

import { presetWindow } from '@/core/utils/calendarModel'
import { MAX_WINDOW_DAYS, daysBetween, isoDaysAgo } from '@/core/utils/dates'
import { recallPeriod, rememberPeriod } from '@/core/utils/periodMemory'

/**
 * @param {object} options
 * @param {import('vue-router').RouteLocationNormalizedLoaded} options.route
 * @param {import('vue-router').Router} options.router
 * @param {object} options.store The monitoring store (the watcher drives it).
 * @returns {{dateFrom: import('vue').Ref<string>, dateTo: import('vue').Ref<string>,
 *   windowTooWide: import('vue').Ref<boolean>,
 *   handleSelect: (item: {nm_id: number}) => void, handleApply: (query: string) => void,
 *   applyPeriod: (window: {from: string, to: string}) => void}}
 */
export function useSearchQuerySync({ route, router, store }) {
  const defaults = recallPeriod(PERIOD_PAGE, periodEdge()) ?? defaultWindow()

  function readSearchQuery(query) {
    const pick = (key) => (typeof query[key] === 'string' ? query[key] : '')
    return {
      sku: pick('sku'),
      date_from: pick('date_from') || defaults.from,
      date_to: pick('date_to') || defaults.to,
    }
  }

  // The period on screen: set by the calendar (`applyPeriod`), and rewound by
  // the watcher on Back/forward.
  const initial = readSearchQuery(route.query)
  const dateFrom = ref(initial.date_from)
  const dateTo = ref(initial.date_to)

  /**
   * Is the chosen window wider than the API will answer for?
   *
   * Asked BEFORE fetching rather than discovered from the answer. The limit is
   * a property of the feature, not a mistake the seller made, and two red
   * «не удалось загрузить» boxes — one for the SKU list, one for the card — is
   * not how a product states its own bounds. The page says the bound in a line
   * of ordinary text instead, and nothing is requested until the range fits.
   */
  const windowTooWide = ref(false)

  // The URL is the single source of truth (deep-linkable, survives refresh and
  // back/forward): handlers only push a new query, this watcher does ALL
  // fetching — the SKU list follows the window, the detail follows sku + window.
  watch(
    () => route.query,
    (query, oldQuery) => {
      if (route.name !== 'monitoring') return // navigating away, not a new search
      const search = readSearchQuery(query)
      const old = oldQuery ? readSearchQuery(oldQuery) : null

      // Back/forward must also rewind the period selector.
      dateFrom.value = search.date_from
      dateTo.value = search.date_to

      windowTooWide.value = daysBetween(search.date_from, search.date_to) > MAX_WINDOW_DAYS
      // Neither request can succeed, and both would fail loudly. The note the
      // page shows instead is the whole answer.
      if (windowTooWide.value) return

      if (!old || old.date_from !== search.date_from || old.date_to !== search.date_to) {
        store.fetchSkuList({ date_from: search.date_from, date_to: search.date_to })
      }

      if (!search.sku) {
        store.reset()
        return
      }
      if (old && JSON.stringify(search) === JSON.stringify(old)) return
      store.fetchProductData(search.sku, { date_from: search.date_from, date_to: search.date_to })
    },
    { immediate: true },
  )

  /** Dropdown pick: analyze this SKU over the drafted window. */
  function handleSelect(item) {
    pushSearch(String(item.nm_id))
  }

  /**
   * «Применить»: apply the drafted period. A raw nm ID in the input is treated
   * as a direct pick; otherwise the currently analyzed SKU (if any) is kept.
   */
  function handleApply(query) {
    const sku = /^\d+$/.test(query) ? query : readSearchQuery(route.query).sku
    pushSearch(sku)
  }

  /**
   * A window from the calendar: apply it at once, keeping the SKU on screen.
   *
   * Same rule as every other handler — it pushes a query and the watcher
   * fetches — so Back rewinds the pick the way it rewinds a search.
   *
   * @param {{from: string, to: string}} window
   */
  function applyPeriod({ from, to }) {
    dateFrom.value = from
    dateTo.value = to
    rememberPeriod(PERIOD_PAGE, from, to, periodEdge())
    pushSearch(readSearchQuery(route.query).sku)
  }

  // `push` (not `replace`) keeps every search reachable via the Back button.
  function pushSearch(sku) {
    router.push({
      query: { ...(sku && { sku }), date_from: dateFrom.value, date_to: dateTo.value },
    })
  }

  return { dateFrom, dateTo, windowTooWide, handleSelect, handleApply, applyPeriod }
}
