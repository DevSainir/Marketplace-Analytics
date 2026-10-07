/**
 * What stands where the SKU card goes while there is none to show.
 *
 * Split out of `MonitoringView` (a component is capped at 250 lines), and a
 * pure function so the order is plain: the window bound leads, said as a bound
 * and not a fault; then a first load, a failure, a search that found nothing.
 * Once a card is on screen none of these replace it — a reload dims it
 * (`BusyRegion`) and a failed one is a line above it.
 */
import { MAX_WINDOW_DAYS } from '@/core/utils/dates'

/**
 * @param {{windowTooWide: boolean, product: ?object,
 *   store: {loading: boolean, error: ?string, notFound: ?string}}} state
 * @returns {{kind: string, text?: string}|null} Props for `DataState`, or `null`.
 */
export function describeDetail({ windowTooWide, product, store }) {
  if (windowTooWide) {
    const text = `Период больше ${MAX_WINDOW_DAYS} дней не показываем — выберите отрезок покороче.`
    return { kind: 'empty', text }
  }
  if (product) return null
  if (store.loading) return { kind: 'loading' }
  if (store.error) return { kind: 'error', text: store.error }
  if (store.notFound)
    return { kind: 'empty', text: `По артикулу «${store.notFound}» ничего не найдено.` }
  return null
}
