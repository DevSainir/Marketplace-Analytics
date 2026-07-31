/**
 * Row shaping and local search/filter for the per-SKU P&L table.
 *
 * Pulled out of `PnlSkuTable.vue` so the component stays under the size limit and
 * the pure data logic can be read (and tested) on its own. It never fetches:
 * it maps the backend's `PnlSkuRow`s to the flat shape the DataTable sorts on,
 * and filters them by the search query and the Тип предмета / Бренд selectors —
 * all view concerns, so the dashboard totals are unaffected.
 */
import { computed, ref } from 'vue'

const num = (value) => (value === null || value === undefined ? null : Number(value))

/** Flatten one backend `PnlSkuRow` to the shape the table renders and sorts on. */
export function toRow(r, isBucket = false) {
  return {
    nmId: r.nm_id,
    saName: r.sa_name,
    subject: r.subject_name || '',
    brand: r.brand_name || '',
    isBucket,
    isExcluded: !!r.is_excluded,
    orders: num(r.orders_units),
    sold: r.sold_units,
    returned: r.returned_units,
    returnPct: num(r.return_rate_pct),
    sales: num(r.revenue_paid),
    averageCheque: num(r.average_cheque),
    sppPct: num(r.spp_pct),
    logistics: num(r.logistics_total),
    logisticsPct: num(r.logistics_pct),
    penalties: num(r.penalties_total),
    penaltyReasons: (r.penalties ?? []).map((p) => ({ reason: p.reason, amount: num(p.amount) })),
    cogs: num(r.cogs),
    advertising: num(r.advertising),
    advertisingPct: num(r.advertising_pct),
    roi: num(r.roi_pct),
    romi: num(r.romi_pct),
    payout: num(r.payout_net),
    profit: num(r.net_profit),
    profitPct: num(r.net_profit_pct),
  }
}

/**
 * Search + Тип предмета / Бренд filtering over the loaded rows.
 *
 * @param {import('vue').Ref<Array>} rows Reactive `PnlSkuRow[]`.
 * @param {import('vue').Ref<object|null>} unallocated The account-level bucket.
 */
export function usePnlSkuRows(rows, unallocated) {
  const query = ref('')
  const subjectFilter = ref('')
  const brandFilter = ref('')

  const distinct = (key) =>
    [...new Set(rows.value.map((r) => r[key]).filter(Boolean))].sort((a, b) =>
      a.localeCompare(b, 'ru'),
    )
  const subjects = computed(() => distinct('subject_name'))
  const brands = computed(() => distinct('brand_name'))

  const isFiltering = computed(
    () => !!(query.value.trim() || subjectFilter.value || brandFilter.value),
  )

  /** The raw `PnlSkuRow`s (no bucket) matching the search + Тип/Бренд filters. */
  const filtered = computed(() => {
    const needle = query.value.trim().toLowerCase()
    let list = rows.value
    if (subjectFilter.value) list = list.filter((r) => r.subject_name === subjectFilter.value)
    if (brandFilter.value) list = list.filter((r) => r.brand_name === brandFilter.value)
    if (needle) {
      list = list.filter((r) =>
        [r.sa_name, String(r.nm_id), r.subject_name, r.brand_name].some((field) =>
          field?.toLowerCase().includes(needle),
        ),
      )
    }
    return list
  })

  const tableRows = computed(() => {
    const mapped = filtered.value.map((r) => toRow(r))
    // The account-level bucket has no SKU identity to filter on — show it only
    // when the list is unfiltered, so a search never strands an orphan row.
    if (unallocated.value && !isFiltering.value) mapped.push(toRow(unallocated.value, true))
    return mapped
  })

  return { query, subjectFilter, brandFilter, subjects, brands, tableRows, filtered, isFiltering }
}

/**
 * Sum the visible (filtered) SKUs into the dashboard shape, for the «по фильтру»
 * view. Only SUMS backend-computed per-row figures — the P&L math itself stays
 * on the backend; this is a spreadsheet-style subtotal of the rows on screen, so
 * it is instant and needs no debounce even while typing in the search.
 *
 * The marked («Не включать») rows are dropped, exactly as the backend dashboard
 * does. Account-level money (storage, subscriptions, the ad invoices) has no SKU
 * to attribute to a filtered subset, so «Прочие удержания» here is the subset's
 * own per-SKU advertising rather than the whole-account deduction line.
 *
 * @param {Array<object>} rows Raw `PnlSkuRow`s passing the current filter.
 */
export function subsetDashboard(rows) {
  const included = rows.filter((r) => !r.is_excluded)
  const n = (v) => (v === null || v === undefined ? 0 : Number(v))
  const sum = (pick) => included.reduce((acc, r) => acc + n(pick(r)), 0)

  const sales = sum((r) => r.revenue_paid)
  const logistics = sum((r) => r.logistics_total)
  const sold = included.reduce((a, r) => a + r.sold_units, 0)
  const returned = included.reduce((a, r) => a + r.returned_units, 0)
  const ads = sum((r) => r.advertising)

  return {
    sales,
    sales_gross: sum((r) => r.sales_amount),
    returns_amount: sum((r) => r.returns_amount),
    sold_units: sold,
    return_rate_pct: sold ? (returned / sold) * 100 : null,
    logistics,
    logistics_pct: sales ? (logistics / sales) * 100 : null,
    cogs: sum((r) => r.cogs),
    uncosted_count: included.filter((r) => r.cost_price === null && r.sold_units > 0).length,
    payout_net: sum((r) => r.payout_net),
    other_deductions: ads,
    advertising: ads,
    excluded_count: rows.filter((r) => r.is_excluded).length,
  }
}
