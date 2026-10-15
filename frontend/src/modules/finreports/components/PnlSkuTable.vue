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
 *
 * It also owns the one «Себестоимость» dialog both projections open from an
 * uncosted article — one dialog, so the table and the cards cannot disagree
 * on how a cost is entered. Without `saveCost` (a read-only member) the rows
 * are still marked, but nothing offers to write.
 */
import { computed, ref, toRefs, watch, watchEffect } from 'vue'

import PnlCostDialog from '@/modules/finreports/components/PnlCostDialog.vue'
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
  /** The payout's currency — what a cost typed here is stated in. */
  currency: { type: String, default: '' },
  /** @type {Function|null} Writes one article's cost; `null` = this member may not. */
  saveCost: { type: Function, default: null },
})

/** «Без себестоимости» — a model, because the dashboard's counter turns it on too. */
const uncostedOnly = defineModel('uncostedOnly', { type: Boolean, default: false })

const emit = defineEmits(['toggle-exclusion', 'dashboard-change', 'load-sizes'])

const { rows, unallocated } = toRefs(props)

// Row shaping + local search/filter live in the composable (keeps this
// component under the size limit).
const {
  query,
  uncostedCount,
  subjectFilter,
  brandFilter,
  groupFilter,
  cut,
  groupsReadable,
  subjects,
  brands,
  articleRows,
  tableRows,
  filtered,
  isFiltering,
} = usePnlSkuRows(rows, unallocated, usePriceBase(), uncostedOnly)

// The last cost filled in empties the filtered list; going back to every
// article says «done» better than an empty table that reads «нет продаж».
watch(uncostedCount, (count) => {
  if (!count) uncostedOnly.value = false
})

/** The article whose cost the dialog asks for. */
const costFor = ref(null)

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
 * и ту же выборку, а выборку знает этот компонент. Складываются артикулы, а не
 * строки на экране: в разбивке по группам артикул стоит в каждой своей группе,
 * и сумма строк посчитала бы его дважды. Счета WB за рекламу
 * передаются отдельно — из них складывается поправка, без которой «Итого»
 * списало бы рекламу дважды (подробности в `sumRows`).
 */
const totals = computed(() =>
  sumRows(articleRows.value, Number(props.baseDashboard?.advertising ?? 0)),
)

/** The first column's head follows the cut. */
const FIRST_HEADERS = { sku: 'Артикул', subject: 'Предмет', brand: 'Бренд', group: 'Группа' }

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
      v-model:cut="cut"
      v-model:uncosted-only="uncostedOnly"
      :uncosted="uncostedCount"
      :groups-readable="groupsReadable"
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
        :can-enter-cost="!!saveCost"
        @toggle-exclusion="emit('toggle-exclusion', $event)"
        @load-sizes="emit('load-sizes', $event)"
        @enter-cost="costFor = $event"
      />

      <PnlSkuDataTable
        ref="table"
        class="hidden sm:block"
        :rows="tableRows"
        :totals="totals"
        :sizes="sizes"
        :rows-per-page="rowsPerPage"
        :first-header="FIRST_HEADERS[cut]"
        :can-enter-cost="!!saveCost"
        @toggle-exclusion="emit('toggle-exclusion', $event)"
        @load-sizes="emit('load-sizes', $event)"
        @enter-cost="costFor = $event"
      />
    </div>
    <PnlCostDialog
      v-if="saveCost"
      :row="costFor"
      :currency="currency"
      :save="saveCost"
      @close="costFor = null"
    />
  </div>
</template>
