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

import { formatSku } from '@/core/utils/format'

const num = (value) => (value === null || value === undefined ? null : Number(value))

/** Flatten one backend `PnlSkuRow` to the shape the table renders and sorts on. */
export function toRow(r, isBucket = false) {
  return {
    nmId: r.nm_id,
    saName: formatSku(r.sa_name),
    // Null on the account-level bucket and on any SKU the monitoring catalogue
    // has not harvested yet; `SkuThumb` renders its own placeholder for both.
    photoUrl: r.photo_url ?? null,
    subject: r.subject_name || '',
    brand: r.brand_name || '',
    isBucket,
    isExcluded: !!r.is_excluded,
    orders: num(r.orders_units),
    sold: r.sold_units,
    returned: r.returned_units,
    returnPct: num(r.return_rate_pct),
    sales: num(r.revenue_seller_price),
    averageCheque: num(r.average_cheque),
    sppPct: num(r.spp_pct),
    logistics: num(r.logistics_total),
    logisticsPct: num(r.logistics_pct),
    penalties: num(r.penalties_total),
    penaltyReasons: (r.penalties ?? []).map((p) => ({ reason: p.reason, amount: num(p.amount) })),
    cogs: num(r.cogs),
    advertising: num(r.advertising),
    advertisingPct: num(r.advertising_pct),
    // Positive magnitude, exactly as the API sends it. Rendering is what
    // gives it the minus sign — a doubly negated deduction adds back.
    adBonus: num(r.ad_bonus),
    advertisingCash: num(r.advertising_cash),
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
 * does. «Прочие удержания» (ad invoices, subscription, transit) is account-level
 * money WB books without a SKU, so it cannot be attributed to a filtered subset —
 * it is carried through from the backend dashboard unchanged, and `filtered` is
 * set so the card can say «на весь счёт».
 *
 * @param {Array<object>} rows Raw `PnlSkuRow`s passing the current filter.
 * @param {object|null} base The backend dashboard, for the account-level figures.
 */
export function subsetDashboard(rows, base = null) {
  const included = rows.filter((r) => !r.is_excluded)
  const n = (v) => (v === null || v === undefined ? 0 : Number(v))
  const sum = (pick) => included.reduce((acc, r) => acc + n(pick(r)), 0)

  const sales = sum((r) => r.revenue_seller_price) // seller price, net of returns
  const paid = sum((r) => r.revenue_paid) // what buyers paid, after СПП
  const logistics = sum((r) => r.logistics_total)
  const sold = included.reduce((a, r) => a + r.sold_units, 0)
  const returned = included.reduce((a, r) => a + r.returned_units, 0)

  return {
    sales,
    paid,
    sold_units: sold,
    return_rate_pct: sold ? (returned / sold) * 100 : null,
    logistics,
    logistics_pct: sales ? (logistics / sales) * 100 : null,
    cogs: sum((r) => r.cogs),
    uncosted_count: included.filter((r) => r.cost_price === null && r.sold_units > 0).length,
    payout_net: sum((r) => r.payout_net),
    // Account-level, not per-SKU — carried from the backend dashboard as-is.
    other_deductions: base ? n(base.other_deductions) : 0,
    advertising: base ? n(base.advertising) : 0,
    excluded_count: rows.filter((r) => r.is_excluded).length,
    filtered: true,
  }
}
