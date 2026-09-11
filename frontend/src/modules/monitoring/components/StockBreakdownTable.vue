<script setup>
import { computed } from 'vue'

import { pivotRows, pivotWarehouses, sizeShare } from '@/modules/monitoring/stockPivot'
import { useWarehouseNameTip } from '@/modules/monitoring/useWarehouseNameTip'

import { vDragScroll } from '@/core/utils/dragScroll'
import { formatNumber } from '@/core/utils/format'

/**
 * Warehouses × sizes stock matrix: a pivot of the backend `StockDetail.cells`
 * payload (latest snapshot day). Columns are warehouses ordered by their
 * total remaining stock — the fullest warehouse on the left; rows are the
 * SKU's sizes; each cell is the remaining quantity of that size at that
 * warehouse. A «Всего» column (frozen on the left, next to the size label)
 * and a «Всего» row carry the per-size / per-warehouse totals.
 *
 * Rendered as a native `<table>` inside the shared `.app-datatable` skin
 * (same approach as MetricsTable.vue): the column order is fixed by the
 * pivot rule and the row count is tiny, so PrimeVue's sortable-column and
 * pagination machinery add nothing here.
 */
const props = defineProps({
  /** `StockDetail.cells`: one entry per size (`chrt_id`) × warehouse. */
  cells: { type: Array, required: true },
  /**
   * Externally imposed row set/order (`[{chrt_id, tech_size}]`) — the two-day
   * comparison passes the UNION of both days' sizes so the side-by-side
   * tables share identical rows. A size absent from this day renders as an
   * all-blank row. `null` = derive rows from own cells (standalone mode).
   */
  sizeOrder: { type: Array, default: null },
  /** Message when the day has no cells at all. */
  emptyMessage: { type: String, default: 'Нет складских остатков по этому SKU.' },
})

const { hoverTip, showNameTip, hideNameTip } = useWarehouseNameTip()

/**
 * Human size label (WB «Размер вещи»); falls back to the raw `chrt_id`
 * until the content catalogue is synced for that size.
 */
function sizeLabel(row) {
  return row.tech_size ?? `chrt ${row.chrt_id}`
}

/**
 * Compact warehouse header: the first 8 letters (WB names like
 * «Электросталь» blow the columns up); the full name shows on hover via
 * the `title` attribute.
 */
function shortWarehouseName(name) {
  return name.length > 8 ? `${name.slice(0, 8)}…` : name
}

const warehouses = computed(() => pivotWarehouses(props.cells))

const rows = computed(() => pivotRows(props.cells, props.sizeOrder, sizeLabel))

const grandTotal = computed(() => warehouses.value.reduce((sum, wh) => sum + wh.total, 0))
</script>

<template>
  <div class="app-datatable">
    <div v-if="!cells.length" class="px-md py-xl text-center text-base text-muted">
      {{ emptyMessage }}
    </div>

    <div v-else v-drag-scroll class="stock-scroll">
      <table>
        <thead>
          <tr>
            <th class="col-size">Размер</th>
            <th class="col-total">Всего</th>
            <th
              v-for="wh in warehouses"
              :key="wh.name"
              class="col-wh"
              @mouseenter="showNameTip($event, wh.name)"
              @mouseleave="hideNameTip"
            >
              {{ shortWarehouseName(wh.name) }}
            </th>
          </tr>
        </thead>

        <tbody>
          <tr v-for="row in rows" :key="row.chrt_id">
            <td class="cell-size font-medium" :title="sizeLabel(row)">{{ sizeLabel(row) }}</td>
            <td
              class="cell-total cell-total--share font-semibold tabular-nums"
              :style="{ '--share': sizeShare(row.total, grandTotal) }"
            >
              {{ row.total ? formatNumber(row.total) : '' }}
            </td>
            <td v-for="wh in warehouses" :key="wh.name" class="tabular-nums">
              <!-- Zeros read as blanks — only real remainders carry a number. -->
              <span v-if="row.quantities[wh.name]">{{
                formatNumber(row.quantities[wh.name])
              }}</span>
            </td>
          </tr>
        </tbody>

        <tfoot>
          <tr>
            <td class="cell-size font-medium">Всего</td>
            <td class="cell-total font-bold tabular-nums">
              {{ grandTotal ? formatNumber(grandTotal) : '' }}
            </td>
            <td v-for="wh in warehouses" :key="wh.name" class="font-semibold tabular-nums">
              {{ wh.total ? formatNumber(wh.total) : '' }}
            </td>
          </tr>
        </tfoot>
      </table>
    </div>

    <!-- Full warehouse name on hover: teleported so the scroll container
         can't clip it (shown only for truncated headers). -->
    <Teleport to="body">
      <div
        v-if="hoverTip"
        class="fixed z-50 rounded-card border border-border-subtle bg-surface px-sm py-xs text-tiny text-primary shadow-card"
        :style="{ left: `${hoverTip.x}px`, top: `${hoverTip.y}px` }"
      >
        {{ hoverTip.name }}
      </div>
    </Teleport>
  </div>
</template>

<style scoped src="./styles/StockBreakdownTable.css"></style>
