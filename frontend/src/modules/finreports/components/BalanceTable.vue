<script setup>
/**
 * «Баланс по товарным остаткам» — the SKU x warehouse stock grid for one day.
 *
 * Rows are SKUs, columns are warehouses, and every cell carries the two figures
 * that make this a balance rather than a stock report: the units still lying
 * there and what they cost the seller to put there (units x cost price).
 *
 * FOUR separate blocks floating over the canvas, not one table with frozen
 * edges: the grid, «Итого по артикулу» beside it, «Итого по складу» beneath it,
 * and «Итого» in the corner. They were sticky panes inside one table first, and
 * that shape kept producing the same two faults — the right pane clipped by the
 * scroll container, and a phantom horizontal scrollbar the panes' own borders
 * added past the container's width. As real blocks each one owns its box, and
 * only the grid scrolls: the panels follow its scroll position through
 * {@link syncPanels}, which is what keeps every total against its row and its
 * column.
 *
 * Тип предмета and Бренд are NOT columns (the columns are warehouses) but stay
 * filterable through the shared P&L toolbar. Ordering and the totals are the
 * composable's: marks apply the instant they are clicked, so both have to be
 * derived on screen rather than fetched (see `useBalanceRows`).
 */
import { computed, ref, toRefs } from 'vue'

import BalanceColumnTotals from '@/modules/finreports/components/BalanceColumnTotals.vue'
import BalanceGrid from '@/modules/finreports/components/BalanceGrid.vue'
import BalanceMarkMenu from '@/modules/finreports/components/BalanceMarkMenu.vue'
import BalanceRowTotals from '@/modules/finreports/components/BalanceRowTotals.vue'
import PnlSkuTableToolbar from '@/modules/finreports/components/PnlSkuTableToolbar.vue'
import { useBalancePins } from '@/modules/finreports/useBalancePins'
import { moneyFormatter, useBalanceRows } from '@/modules/finreports/useBalanceRows'

import { formatNumber } from '@/core/utils/format'

const props = defineProps({
  /** The `/finreports/balance` payload; `null` while it loads. */
  balance: { type: Object, default: null },
})

const emit = defineEmits(['mark'])

const { balance } = toRefs(props)

const {
  query,
  subjectFilter,
  brandFilter,
  subjects,
  brands,
  columns,
  tableRows,
  totals,
  isFiltering,
  pinnedCount,
  uncountedCount,
  isGroupBoundary,
  isRowBoundary,
} = useBalanceRows(balance)

const { menu, openMenu, togglePin, toggleUncounted, hoverTip, showNameTip, hideNameTip } =
  useBalancePins({ onMark: (mark) => emit('mark', mark) })

const money = computed(() => moneyFormatter(balance.value?.currency ?? ''))

/** Ordinary columns: everything between the pinned ones and the uncounted. */
const ordinaryCount = computed(
  () => columns.value.length - pinnedCount.value - uncountedCount.value,
)

const grid = ref(null)
const rowTotals = ref(null)
const columnTotals = ref(null)

/** Follow the grid: the row panel takes its vertical offset, the column panel
 *  its horizontal one. Only the grid has scrollbars, so this cannot loop. */
function syncPanels() {
  const source = grid.value?.scroller
  if (!source) return
  if (rowTotals.value?.scroller) rowTotals.value.scroller.scrollTop = source.scrollTop
  if (columnTotals.value?.scroller) columnTotals.value.scroller.scrollLeft = source.scrollLeft
}

/** A wheel over a panel still scrolls the grid — the panels have no scrollbars
 *  of their own, and a dead zone over «Итого по артикулу» reads as a freeze. */
function forwardWheel(event) {
  const target = grid.value?.scroller
  if (!target) return
  event.preventDefault()
  target.scrollTop += event.deltaY
  target.scrollLeft += event.deltaX
  syncPanels()
}
</script>

<template>
  <div class="balance-layout">
    <div class="balance-block toolbar-block">
      <PnlSkuTableToolbar
        v-model:query="query"
        v-model:subject="subjectFilter"
        v-model:brand="brandFilter"
        :subjects="subjects"
        :brands="brands"
        :page-sizes="[]"
      />
    </div>

    <div
      v-if="!tableRows.length"
      class="balance-block px-md py-xl text-center text-base text-muted"
    >
      {{ isFiltering ? 'Нет артикулов по фильтру' : 'Нет остатков на выбранный день' }}
    </div>

    <div v-else class="balance-blocks">
      <BalanceGrid
        ref="grid"
        :columns="columns"
        :rows="tableRows"
        :money="money"
        :pinned-count="pinnedCount"
        :uncounted-count="uncountedCount"
        :ordinary-count="ordinaryCount"
        :is-group-boundary="isGroupBoundary"
        :is-row-boundary="isRowBoundary"
        @scroll="syncPanels"
        @open-menu="openMenu($event.event, $event.target)"
        @show-tip="showNameTip($event.event, $event.name, $event.limit)"
        @hide-tip="hideNameTip"
      />

      <BalanceRowTotals
        ref="rowTotals"
        :rows="tableRows"
        :money="money"
        :is-row-boundary="isRowBoundary"
        @wheel="forwardWheel"
      />

      <BalanceColumnTotals
        ref="columnTotals"
        :warehouses="totals.warehouses"
        :money="money"
        :is-group-boundary="isGroupBoundary"
        @wheel="forwardWheel"
      />

      <div class="balance-block corner-block">
        <div class="corner-label">Итого</div>
        <div class="corner-value tabular-nums">{{ formatNumber(totals.quantity) }} шт</div>
        <div class="corner-value corner-money tabular-nums">{{ money(totals.balance) }}</div>
      </div>
    </div>

    <BalanceMarkMenu
      :menu="menu"
      :tip="hoverTip"
      @toggle-pin="togglePin"
      @toggle-uncounted="toggleUncounted"
    />
  </div>
</template>

<style scoped src="./styles/BalanceTable.css"></style>
