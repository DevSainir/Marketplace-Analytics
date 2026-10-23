/**
 * State and formatting of the "By SKU" table — everything that is not
 * markup.
 *
 * Pulled out of `PnlSkuDataTable.vue` for the same reason the cards were: a
 * couple of dozen column definitions already fill the file, and any logic next
 * to them stops being readable. Here: which articles are expanded, the order
 * and the page with sizes under their articles, and what the "Total" row looks
 * like; there: only the columns.
 */
import { computed, ref, watch } from 'vue'

import { formatNumber } from '@/core/utils/format'
import { pct, usePnlMoney } from '@/modules/finreports/pnlFormat'
import { sortRows, treeRows } from '@/modules/finreports/pnlSkuTree'
import { TOTAL_LABEL } from '@/modules/finreports/usePnlSkuRows'

/**
 * Which articles are expanded, in the shape PrimeVue expects (a map by
 * `dataKey`), and asking for each open article's sizes whenever it has none.
 *
 * Asking only on the click was the other half of the endless sizes
 * spinner: the store drops every article's sizes when the report reloads —
 * a new period, or an "Exclude from total" toggle — while the rows stay
 * open, so an open row was left with nothing and nothing asking for it. The
 * watch re-asks for exactly those; the store ignores an article already
 * loaded or loading, so it costs nothing otherwise.
 *
 * @param {(nmId: number) => void} onOpen Asks for one article's sizes.
 * @param {() => object} sizesOf The store's nm_id -> state map.
 */
export function useExpandedSkus(onOpen, sizesOf = () => ({})) {
  const expanded = ref({})

  function toggle(nmId) {
    if (expanded.value[nmId]) {
      const rest = { ...expanded.value }
      delete rest[nmId]
      expanded.value = rest
      return
    }
    expanded.value = { ...expanded.value, [nmId]: true }
    onOpen(nmId)
  }

  watch([expanded, sizesOf], ([open, sizes]) => {
    for (const nmId of Object.keys(open)) {
      if (!sizes[nmId]) onOpen(Number(nmId))
    }
  })

  return { expanded, toggle }
}

/**
 * The "Total" row's label, naming how many marked rows it leaves out. Prose,
 * so it never goes through `formatSku`.
 *
 * @param {number} [excluded] Rows marked "Exclude from total".
 */
export function totalLabel(excluded = 0) {
  return excluded ? `${TOTAL_LABEL} (${excluded} excluded)` : TOTAL_LABEL
}

/**
 * Ready-made cells of the "Total" row. Built in advance so that each column
 * carries one `:footer`, not a block of formatting inside the template.
 *
 * @param {import('vue').Ref<object|null>} totals A row from `sumRows`.
 */
export function useFooterCells(totals) {
  const { money } = usePnlMoney()
  return computed(() => {
    const t = totals.value
    if (!t) return {}
    return {
      saName: totalLabel(t.excludedCount),
      orders: t.orders === null ? '' : formatNumber(t.orders),
      sold: formatNumber(t.sold),
      returnPct: pct(t.returnPct),
      buyoutPct: pct(t.buyoutPct),
      sales: money(t.sales),
      averageCheque: money(t.averageCheque),
      sppPct: pct(t.sppPct),
      logistics: `${money(t.logistics)} (${pct(t.logisticsPct)})`,
      logisticsPerSale: money(t.logisticsPerSale),
      penalties: money(t.penalties),
      cogs: money(t.cogs),
      advertising: money(t.advertising),
      advertisingPct: pct(t.advertisingPct),
      adBonus: t.adBonus ? `-${money(t.adBonus)}` : money(t.adBonus),
      roi: pct(t.roi),
      payout: money(t.payout),
    }
  })
}

/**
 * Sorting, the page and sizes under their articles — what PrimeVue used to do
 * itself (why it no longer does is in `pnlSkuTree`).
 *
 * @param {object} src
 * @param {import('vue').Ref<Array>} src.rows Articles after filters.
 * @param {() => number} src.perPage Rows per page.
 * @param {import('vue').Ref<object>} src.expanded Expanded articles.
 * @param {() => object} src.sizes Sizes from the store.
 * @param {() => string} src.base The page's price base.
 */
export function useSkuTreePage({ rows, perPage, expanded, sizes, base }) {
  const sortField = ref(null)
  const sortOrder = ref(null)
  /** The page's first article — counted in articles, not rows. */
  const first = ref(0)

  // A filter narrowed the selection — a page past its end would show an empty table.
  watch(
    () => rows.value.length,
    (length) => {
      if (first.value >= length) first.value = 0
    },
  )
  // A new order starts from the first page, as PrimeVue did.
  watch([sortField, sortOrder], () => {
    first.value = 0
  })

  const sorted = computed(() => sortRows(rows.value, sortField.value, sortOrder.value))
  const view = computed(() =>
    treeRows(
      sorted.value.slice(first.value, first.value + perPage()),
      expanded.value,
      sizes(),
      base(),
    ),
  )
  return { sortField, sortOrder, first, view }
}
