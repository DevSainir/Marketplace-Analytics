<script setup>
/**
 * The «По артикулам» cut of the report: the toolbar, and whichever projection
 * of the rows the viewport can carry.
 *
 * Two projections, one set of rows — `PnlSkuDataTable` on a desktop and
 * `PnlSkuCards` below `sm`, both fed the same `tableRows`, so the search and
 * the Тип предмета / Бренд filters above them apply to both without being
 * wired twice.
 *
 * Every figure is the backend's — this only formats, filters and sorts. Search
 * and the filters are purely local over the already-loaded rows (like
 * monitoring's SkuSearchSelect); they never re-fetch and never change the
 * dashboard, which reflects the persisted exclusion marks.
 */
import { computed, ref, toRefs, watchEffect } from 'vue'

import PnlSkuCards from '@/modules/finreports/components/PnlSkuCards.vue'
import PnlSkuDataTable from '@/modules/finreports/components/PnlSkuDataTable.vue'
import PnlSkuTableToolbar from '@/modules/finreports/components/PnlSkuTableToolbar.vue'
import { usePriceBase } from '@/modules/finreports/priceBase'
import { subsetDashboard, sumRows, usePnlSkuRows } from '@/modules/finreports/usePnlSkuRows'

const PAGE_SIZES = [50, 100, 150, 200]

const props = defineProps({
  /** @type {Array<object>} `PnlSkuRow` per SKU. */
  rows: { type: Array, default: () => [] },
  /** @type {object|null} The account-level bucket (rendered as the last row). */
  unallocated: { type: Object, default: null },
  /** @type {object|null} The backend dashboard, for the account-level «Прочие
   *  удержания» the «по фильтру» subtotal carries through unchanged. */
  baseDashboard: { type: Object, default: null },
  /** @type {object} `nm_id -> {loading, error, data}` — the opened size tables. */
  sizes: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['toggle-exclusion', 'dashboard-change', 'load-sizes'])

const { rows, unallocated } = toRefs(props)

// Row shaping + local search/filter live in the composable (keeps this
// component under the size limit).
const {
  query,
  subjectFilter,
  brandFilter,
  groupFilter,
  subjects,
  brands,
  tableRows,
  filtered,
  isFiltering,
} = usePnlSkuRows(rows, unallocated, usePriceBase())

// Tell the parent to swap the dashboard to a «по фильтру» subtotal while a
// filter/search is active, and back to the backend one when it clears. Summing
// the visible rows is instant, so the search needs no debounce.
watchEffect(() => {
  emit(
    'dashboard-change',
    isFiltering.value ? subsetDashboard(filtered.value, props.baseDashboard) : null,
  )
})

/**
 * Строка «Итого» — сумма того, что сейчас в таблице.
 *
 * Считается здесь, а не в проекции: карточки и таблица должны показывать одну
 * и ту же выборку, а выборку знает этот компонент. Счета WB за рекламу
 * передаются отдельно — из них складывается поправка, без которой «Итого»
 * списало бы рекламу дважды (подробности в `sumRows`).
 */
const totals = computed(() =>
  sumRows(tableRows.value, Number(props.baseDashboard?.advertising ?? 0)),
)

const table = ref(null)
const rowsPerPage = ref(PAGE_SIZES[0])

function setPageSize(value) {
  rowsPerPage.value = Number(value)
  // Reset the paginator: keeping a stale offset can strand the view past the
  // last page of the new layout.
  if (table.value) table.value.first = 0
}
</script>

<template>
  <div>
    <PnlSkuTableToolbar
      v-model:query="query"
      v-model:subject="subjectFilter"
      v-model:brand="brandFilter"
      v-model:group-ids="groupFilter"
      :page-size="rowsPerPage"
      :page-sizes="PAGE_SIZES"
      :subjects="subjects"
      :brands="brands"
      @update:page-size="setPageSize"
    />
    <div class="app-datatable">
      <!-- Below `sm` the eighteen columns become one card per SKU. The switch is a
         capability threshold, not a phone tweak, so it sits at `sm` rather than
         at `phone:` — see the phone-layout skill. Both read `tableRows`, so the
         toolbar above filters them together. -->
      <PnlSkuCards
        class="sm:hidden"
        :rows="tableRows"
        :totals="totals"
        :sizes="sizes"
        @toggle-exclusion="emit('toggle-exclusion', $event)"
        @load-sizes="emit('load-sizes', $event)"
      />

      <PnlSkuDataTable
        ref="table"
        class="hidden sm:block"
        :rows="tableRows"
        :totals="totals"
        :sizes="sizes"
        :rows-per-page="rowsPerPage"
        @toggle-exclusion="emit('toggle-exclusion', $event)"
        @load-sizes="emit('load-sizes', $event)"
      />
    </div>
  </div>
</template>
