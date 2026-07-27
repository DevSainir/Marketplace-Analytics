/**
 * Two-way sync between the monitoring page's search state and the URL.
 *
 * The URL is the single source of truth, deliberately: a SKU plus a window is
 * exactly what people paste to each other ("посмотри M-TRX01-BLK за прошлую
 * неделю"), so the page has to restore fully from a link and every search has
 * to leave one behind. Back/forward then work for free — the watcher re-runs on
 * any query change, whoever caused it — and the handlers stay trivial, because
 * they only push a query and never fetch.
 *
 * That asymmetry is the rule worth keeping: HANDLERS PUSH, THE WATCHER FETCHES.
 * A handler that also fetched would double-fetch on its own navigation and
 * fetch nothing at all on Back.
 *
 * Extracted from `MonitoringView` because routing is not what the page is
 * about, and because these ordering rules deserve a place of their own.
 */
import { ref, watch } from 'vue'

/**
 * @param {object} options
 * @param {import('vue-router').RouteLocationNormalizedLoaded} options.route
 * @param {import('vue-router').Router} options.router
 * @param {object} options.store The monitoring store (the watcher drives it).
 * @param {{from: string, to: string}} options.defaults Window defaults, applied
 *   when the URL omits them.
 * @returns {{dateFrom: import('vue').Ref<string>, dateTo: import('vue').Ref<string>,
 *   handleSelect: (item: {nm_id: number}) => void, handleApply: (query: string) => void}}
 */
export function useSearchQuerySync({ route, router, store, defaults }) {
  function readSearchQuery(query) {
    const pick = (key) => (typeof query[key] === 'string' ? query[key] : '')
    return {
      sku: pick('sku'),
      date_from: pick('date_from') || defaults.from,
      date_to: pick('date_to') || defaults.to,
    }
  }

  // Draft period: edited freely, takes effect on «Применить» or on picking a SKU.
  const initial = readSearchQuery(route.query)
  const dateFrom = ref(initial.date_from)
  const dateTo = ref(initial.date_to)

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

  // `push` (not `replace`) keeps every search reachable via the Back button.
  function pushSearch(sku) {
    router.push({
      query: { ...(sku && { sku }), date_from: dateFrom.value, date_to: dateTo.value },
    })
  }

  return { dateFrom, dateTo, handleSelect, handleApply }
}
