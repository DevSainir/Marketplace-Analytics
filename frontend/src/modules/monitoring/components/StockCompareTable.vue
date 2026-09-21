<script setup>
import { computed } from 'vue'

import { pivotRows, pivotWarehouses, sizeShare } from '@/modules/monitoring/stockPivot'
import { useStockRibbonLayout } from '@/modules/monitoring/useStockRibbonLayout'
import { useWarehouseNameTip } from '@/modules/monitoring/useWarehouseNameTip'

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
    const warehouses = pivotWarehouses(day.cells)
    return {
      ...day,
      warehouses,
      rows: pivotRows(day.cells, props.sizeOrder, sizeLabel),
      grandTotal: warehouses.reduce((sum, warehouse) => sum + warehouse.total, 0),
    }
  }),
)

const hasStock = computed(() => columns.value.some((day) => day.warehouses.length))

/** One day's warehouse column width: its share of the day's own group. */
function warehouseColumnWidth(day) {
  return `calc((var(--group-w) - var(--col-total-w)) / ${day.warehouses.length})`
}

const { root, scroll, groupWidth } = useStockRibbonLayout({ daysSource: () => props.days })
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
            <col class="col-total" />
            <col
              v-for="wh in day.warehouses"
              :key="`${day.key}:${wh.name}`"
              :style="{ width: warehouseColumnWidth(day) }"
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
              :colspan="day.warehouses.length + 1"
            >
              {{ day.label }}
              <span v-if="!day.warehouses.length" class="text-muted">· нет остатков</span>
            </th>
          </tr>
          <!-- Row 2: that day's «Всего», then the warehouses it stocked. -->
          <tr>
            <template v-for="day in columns" :key="day.key">
              <th class="col-total day-start">Всего</th>
              <th
                v-for="wh in day.warehouses"
                :key="`${day.key}:${wh.name}`"
                class="col-wh"
                @mouseenter="showNameTip($event, wh.name)"
                @mouseleave="hideNameTip"
              >
                {{ shortWarehouseName(wh.name) }}
              </th>
            </template>
          </tr>
        </thead>

        <tbody>
          <tr v-for="(size, index) in sizeOrder" :key="size.chrt_id">
            <td class="cell-size font-medium" :title="sizeLabel(size)">{{ sizeLabel(size) }}</td>
            <template v-for="day in columns" :key="day.key">
              <td
                class="cell-total day-start font-semibold tabular-nums"
                :style="{ '--share': sizeShare(day.rows[index]?.total, day.grandTotal) }"
              >
                {{ day.rows[index]?.total ? formatNumber(day.rows[index].total) : '' }}
              </td>
              <td v-for="wh in day.warehouses" :key="`${day.key}:${wh.name}`" class="tabular-nums">
                <!-- Zeros read as blanks — only real remainders carry a number. -->
                <span v-if="day.rows[index]?.quantities[wh.name]">{{
                  formatNumber(day.rows[index].quantities[wh.name])
                }}</span>
              </td>
            </template>
          </tr>
        </tbody>

        <tfoot>
          <tr>
            <td class="cell-size font-medium">Всего</td>
            <template v-for="day in columns" :key="day.key">
              <td class="cell-total day-start font-bold tabular-nums">
                {{ day.grandTotal ? formatNumber(day.grandTotal) : '' }}
              </td>
              <td
                v-for="wh in day.warehouses"
                :key="`${day.key}:${wh.name}`"
                class="font-semibold tabular-nums"
              >
                {{ wh.total ? formatNumber(wh.total) : '' }}
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
        class="fixed z-50 rounded-card border border-border-subtle bg-surface px-sm py-xs text-tiny text-primary shadow-card"
        :style="{ left: `${hoverTip.x}px`, top: `${hoverTip.y}px` }"
      >
        {{ hoverTip.name }}
      </div>
    </Teleport>
  </div>
</template>

<style scoped src="./styles/StockCompareTable.css"></style>
