<script setup>
import { computed } from 'vue'

import {
  DAYS_PER_SCREEN,
  dayColumns,
  isSingleWarehouse,
  pivotRows,
  pivotWarehouses,
  sizeShare,
} from '@/modules/labs/stockPivot'
import { vFitInside } from '@/core/utils/tipFit'
import { useStockRibbonLayout } from '@/modules/labs/useStockRibbonLayout'
import { useWarehouseNameTip } from '@/modules/labs/useWarehouseNameTip'

import { vDragScroll } from '@/core/utils/dragScroll'
import { formatNumber } from '@/core/utils/format'

/**
 * Sizes × (day × warehouses) stock matrix: ONE grid for the whole period.
 *
 * It used to be a table per day, two of them side by side — each with its own
 * size column, its own scroll container and its own day picker. This is a
 * single table arranged like the daily metrics matrix: the size column frozen
 * on the left, one column GROUP per day, EXACTLY two days on screen and the
 * rest of the period a horizontal scroll away, newest day first.
 *
 * Each day shows ONLY the warehouses that held stock THAT day. A seller's
 * warehouse list over a quarter runs to dozens, nearly all of them long since
 * emptied, and carrying the union would spend the width of every day on columns
 * that are blank on the day you are looking at.
 *
 * Which is why the widths come from a `<colgroup>` and not from the cells. Days
 * hold different numbers of columns, and a table left to itself gives every
 * COLUMN an equal share — so the day with twelve warehouses would be three
 * times the width of the day with four and «two days on screen» would mean
 * whatever the data felt like. The colgroup gives every day the same measured
 * width and lets it divide that between its own warehouses. (The width has to
 * be in px: a `calc()` mixing a percentage into a `<col>` is dropped, which is
 * what `--group-w` and the observer below are for.)
 *
 * LAB: a seller with ONE warehouse gets no «Всего» (it would repeat the only
 * column) and five days a screen instead of two — see `DAYS_PER_SCREEN`.
 *
 * Native `<table>`, same reasoning as MetricsTable.vue: fixed column order, no
 * sorting and no pagination, so PrimeVue's machinery would add only overhead.
 */
const props = defineProps({
  /**
   * The days to render, oldest first.
   * @type {Array<{key: string, label: string, cells: object[]}>}
   */
  days: { type: Array, required: true },
  /**
   * The shared row set (`[{chrt_id, tech_size}]`) — the union of every day's
   * sizes, so a size missing from one day renders as a blank cell there.
   */
  sizeOrder: { type: Array, default: () => [] },
  /**
   * LAB-ONLY debug knob: render exactly this many warehouse columns per day
   * (the fullest ones), to look at the grid at any width. No folding, no
   * remainder — «Всего» keeps the whole day's figure. `null` = all of them.
   */
  warehouseLimit: { type: Number, default: null },
  /** Message when not one day of the period holds any stock. */
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
 * «Электросталь» blow the columns up); the full name shows on hover.
 */
function shortWarehouseName(name) {
  return name.length > 8 ? `${name.slice(0, 8)}…` : name
}

/** Per day: the warehouses it actually stocked, its rows, and its total. */
const columns = computed(() =>
  props.days.map((day) => {
    const all = pivotWarehouses(day.cells)
    return {
      ...day,
      warehouses: props.warehouseLimit ? all.slice(0, props.warehouseLimit) : all,
      rows: pivotRows(day.cells, props.sizeOrder, sizeLabel),
      grandTotal: all.reduce((sum, warehouse) => sum + warehouse.total, 0),
    }
  }),
)

const hasStock = computed(() => columns.value.some((day) => day.warehouses.length))

const single = computed(() => isSingleWarehouse(columns.value))

/** One column's width: «Всего» is fixed, the warehouses share the rest. */
function columnWidth(day, column) {
  if (column.kind === 'total') return 'var(--col-total-w)'
  if (single.value) return 'var(--group-w)'
  return `calc((var(--group-w) - var(--col-total-w)) / ${day.warehouses.length})`
}

const { root, scroll, groupWidth } = useStockRibbonLayout({
  daysSource: () => props.days,
  perScreen: () => (single.value ? DAYS_PER_SCREEN.single : DAYS_PER_SCREEN.regular),
})
</script>

<template>
  <div
    ref="root"
    class="app-datatable"
    :style="{ '--days': days.length, ...(groupWidth ? { '--group-w': `${groupWidth}px` } : {}) }"
  >
    <div v-if="!hasStock" class="px-md py-xl text-center text-base text-muted">
      {{ emptyMessage }}
    </div>

    <div v-else ref="scroll" v-drag-scroll class="stock-scroll">
      <table>
        <!-- The widths live here, not on the cells: see the note above. -->
        <colgroup>
          <col class="col-size" />
          <template v-for="day in columns" :key="day.key">
            <col
              v-for="column in dayColumns(day, single)"
              :key="`${day.key}:${column.id}`"
              :style="{ width: columnWidth(day, column) }"
            />
          </template>
        </colgroup>

        <thead>
          <!-- Row 1: one date spanning each day's whole group. -->
          <tr>
            <th class="col-size" rowspan="2">Размер</th>
            <th
              v-for="day in columns"
              :key="day.key"
              class="col-day day-start"
              :colspan="dayColumns(day, single).length"
            >
              {{ day.label }}
              <span v-if="!day.warehouses.length" class="text-muted">· нет остатков</span>
            </th>
          </tr>
          <!-- Row 2: that day's «Всего» (unless single), then its warehouses. -->
          <tr>
            <template v-for="day in columns" :key="day.key">
              <th
                v-for="(column, i) in dayColumns(day, single)"
                :key="`${day.key}:${column.id}`"
                :class="[column.kind === 'total' ? 'col-total' : 'col-wh', i ? '' : 'day-start']"
                @mouseenter="column.wh && showNameTip($event, column.wh.name)"
                @mouseleave="hideNameTip"
              >
                {{
                  column.kind === 'total'
                    ? 'Всего'
                    : column.wh
                      ? shortWarehouseName(column.wh.name)
                      : ''
                }}
              </th>
            </template>
          </tr>
        </thead>

        <tbody>
          <tr v-for="(size, index) in sizeOrder" :key="size.chrt_id">
            <td class="cell-size font-medium" :title="sizeLabel(size)">{{ sizeLabel(size) }}</td>
            <template v-for="day in columns" :key="day.key">
              <td
                v-for="(column, i) in dayColumns(day, single)"
                :key="`${day.key}:${column.id}`"
                class="tabular-nums"
                :class="[
                  column.kind === 'total' ? 'cell-total font-semibold' : '',
                  i ? '' : 'day-start',
                ]"
                :style="
                  column.kind === 'total'
                    ? { '--share': sizeShare(day.rows[index]?.total, day.grandTotal) }
                    : null
                "
              >
                <template v-if="column.kind === 'total'">
                  {{ day.rows[index]?.total ? formatNumber(day.rows[index].total) : '' }}
                </template>
                <!-- Zeros read as blanks — only real remainders carry a number. -->
                <span v-else-if="column.wh && day.rows[index]?.quantities[column.wh.name]">{{
                  formatNumber(day.rows[index].quantities[column.wh.name])
                }}</span>
              </td>
            </template>
          </tr>
        </tbody>

        <tfoot>
          <tr>
            <td class="cell-size font-medium">Всего</td>
            <template v-for="day in columns" :key="day.key">
              <td
                v-for="(column, i) in dayColumns(day, single)"
                :key="`${day.key}:${column.id}`"
                class="tabular-nums"
                :class="[
                  column.kind === 'total' ? 'cell-total font-bold' : 'font-semibold',
                  i ? '' : 'day-start',
                ]"
              >
                <template v-if="column.kind === 'total'">
                  {{ day.grandTotal ? formatNumber(day.grandTotal) : '' }}
                </template>
                <template v-else-if="column.wh?.total">{{
                  formatNumber(column.wh.total)
                }}</template>
              </td>
            </template>
          </tr>
        </tfoot>
      </table>
    </div>

    <!-- Full warehouse name on hover: teleported so the scroll container
         can't clip it (shown only for truncated headers). -->
    <Teleport to="body">
      <div
        v-if="hoverTip"
        v-fit-inside="hoverTip.area"
        class="fixed z-50 rounded-card border border-border-subtle bg-surface px-sm py-xs text-tiny text-primary shadow-card"
        :style="{ left: `${hoverTip.x}px`, top: `${hoverTip.y}px` }"
      >
        {{ hoverTip.name }}
      </div>
    </Teleport>
  </div>
</template>

<style scoped src="./styles/StockCompareTable.css"></style>
