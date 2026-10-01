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
import { atBase, shareOf } from '@/modules/finreports/priceBase'

const num = (value) => (value === null || value === undefined ? null : Number(value))

/**
 * Flatten one backend `PnlSkuRow` to the shape the table renders and sorts on.
 *
 * `sales` is the revenue at the chosen price base, and every share and the
 * average cheque are taken from it here rather than from the backend's
 * seller-price percentages — the same division at either base, so the two
 * cannot drift apart.
 *
 * @param {object} r The backend row.
 * @param {boolean} [isBucket] The account-level «Без привязки к артикулу» row.
 * @param {string} [base] `'seller'` or `'paid'` — see `priceBase.js`.
 */
export function toRow(r, isBucket = false, base = 'seller') {
  const seller = num(r.revenue_seller_price)
  const paid = num(r.revenue_paid)
  const sales = atBase(base, seller, paid)
  const net = r.sold_units - r.returned_units
  const advertising = num(r.advertising)
  const profit = num(r.net_profit)
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
    // Доставки к покупателю — знаменатель «Выкупа». Нужны строке «Итого»:
    // выкуп суммы считается от сложенных штук, а не как средний процент.
    delivered: r.delivered_units ?? 0,
    buyoutPct: num(r.buyout_pct),
    sales,
    // Обе базы — строке «Итого»: доли она пересчитывает от сложенных сумм
    // (доля суммы — не сумма долей), а СПП это разница между ними.
    seller,
    paid,
    averageCheque: net && sales !== null ? sales / net : null,
    sppPct: num(r.spp_pct),
    logistics: num(r.logistics_total),
    logisticsPct: shareOf(num(r.logistics_total), sales),
    penalties: num(r.penalties_total),
    penaltyReasons: (r.penalties ?? []).map((p) => ({ reason: p.reason, amount: num(p.amount) })),
    cogs: num(r.cogs),
    advertising,
    advertisingPct: shareOf(advertising, sales),
    // Positive magnitude, exactly as the API sends it. Rendering is what
    // gives it the minus sign — a doubly negated deduction adds back.
    adBonus: num(r.ad_bonus),
    advertisingCash: num(r.advertising_cash),
    roi: num(r.roi_pct),
    payout: num(r.payout_net),
    profit,
    profitPct: shareOf(profit, sales),
  }
}

/**
 * Search + Тип предмета / Бренд filtering over the loaded rows.
 *
 * @param {import('vue').Ref<Array>} rows Reactive `PnlSkuRow[]`.
 * @param {import('vue').Ref<object|null>} unallocated The account-level bucket.
 * @param {() => string} [base] The chosen price base — see `priceBase.js`.
 */
export function usePnlSkuRows(rows, unallocated, base = () => 'seller') {
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
    const mapped = filtered.value.map((r) => toRow(r, false, base()))
    // The account-level bucket has no SKU identity to filter on — show it only
    // when the list is unfiltered, so a search never strands an orphan row.
    if (unallocated.value && !isFiltering.value) {
      mapped.push(toRow(unallocated.value, true, base()))
    }
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
    returned_units: returned,
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

/**
 * Сумма по каждому столбцу того, что сейчас на экране — строка «Итого».
 *
 * Складываются только суммы; все доли пересчитываются от сложенных баз, потому
 * что доля суммы это не сумма долей: средняя «Доля логистики» по сорока
 * артикулам ничего не значит, а логистика всего периода к выручке всего периода
 * значит. Отмеченные «Не включать в общий счёт» строки в сумму не идут — это и
 * есть общий счёт, тот же, что в карточках наверху.
 *
 * Отдельная арифметика у одной цифры — «Чистая прибыль». Реклама приходит от WB
 * дважды: счётом «Оказание услуг «WB Продвижение»», уже удержанным внутри «К
 * перечислению», и открутом по дням из статистики кампаний. В строке артикула
 * вычитается только открут (счёт не несёт артикула), и это верно. Но как только
 * в сумму попадает строка «Без привязки к артикулу» — а вместе с ней и удержанный
 * счёт, — вычесть сверху ещё и открут значит списать рекламу дважды. Поэтому
 * счета возвращаются обратно ровно в этом случае: это та же поправка, которую
 * бэкенд делает в `build_sku_report`, и без неё «Итого» разошлось бы с его
 * итогом на всю рекламу периода (на живом окне это были миллионы). И так же, как
 * там, — только когда открут известен: без него счёт единственная цифра рекламы,
 * и вернуть его, ничего не вычтя взамен, значит завысить прибыль на все счета.
 *
 * @param {Array<object>} rows Плоские строки из {@link toRow} — то, что отрисовано.
 * @param {number} adInvoices Удержанные WB счета за рекламу («ВБ.Продвижение»)
 *   за период, из дашборда. Применяются, только если в `rows` есть строка счёта.
 * @returns {object|null} Строка той же формы, что и остальные, либо `null` на пустой таблице.
 */
export function sumRows(rows, adInvoices = 0) {
  const included = rows.filter((r) => !r.isExcluded)
  if (!included.length) return null

  const n = (v) => (v === null || v === undefined ? 0 : Number(v))
  const sum = (key) => included.reduce((acc, r) => acc + n(r[key]), 0)
  /** Сумма, но `null`, если её не знает ни одна строка («нет данных» ≠ ноль). */
  const known = (key) =>
    included.some((r) => r[key] !== null && r[key] !== undefined) ? sum(key) : null
  const share = (part, whole) => (whole ? (part / whole) * 100 : null)

  const sold = sum('sold')
  const returned = sum('returned')
  const delivered = sum('delivered')
  const sales = sum('sales')
  const seller = sum('seller')
  const paid = sum('paid')
  const net = sold - returned
  const logistics = sum('logistics')
  const cogs = known('cogs')
  const advertising = known('advertising')
  const advertisingCash = known('advertisingCash')
  const payout = sum('payout')

  // Без открута подменять нечем: счёт остаётся внутри «К перечислению».
  const returnInvoices = included.some((r) => r.isBucket) && advertisingCash !== null
  const profit =
    cogs === null ? null : payout + (returnInvoices ? n(adInvoices) : 0) - cogs - n(advertisingCash)

  return {
    nmId: 0,
    saName: 'Итого',
    isTotals: true,
    isBucket: false,
    isExcluded: false,
    excludedCount: rows.length - included.length,
    orders: known('orders'),
    sold,
    returned,
    returnPct: share(returned, sold),
    delivered,
    buyoutPct: share(sold, delivered),
    sales,
    seller,
    paid,
    averageCheque: net ? sales / net : null,
    sppPct: share(seller - paid, seller),
    logistics,
    logisticsPct: share(logistics, sales),
    penalties: sum('penalties'),
    penaltyReasons: [],
    cogs,
    advertising,
    advertisingPct: advertising === null ? null : share(advertising, sales),
    adBonus: known('adBonus'),
    advertisingCash,
    roi: profit === null || !cogs ? null : share(profit, cogs),
    payout,
    profit,
    profitPct: profit === null ? null : share(profit, sales),
  }
}
