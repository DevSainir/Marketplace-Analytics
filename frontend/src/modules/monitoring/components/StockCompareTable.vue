<script setup>
import { computed } from 'vue'

import { pivotRows, sharedWarehouses, sizeShare } from '@/modules/monitoring/stockPivot'
import { useWarehouseNameTip } from '@/modules/monitoring/useWarehouseNameTip'

import { vDragScroll } from '@/core/utils/dragScroll'
import { formatNumber } from '@/core/utils/format'

/**
 * Sizes × (day × warehouses) stock matrix: ONE grid for the whole comparison.
 *
 * It used to be two tables side by side, one per day, each with its own size
 * column — which meant two scroll containers, two row sets kept in sync by
 * hand, and the size labels printed twice. This is a single table built like
 * the daily metrics matrix: the size column is frozen on the left, every day is
 * a column GROUP («Всего» + that day's warehouses), and the groups are sized so
 * both days sit on screen at once. Only when a day holds more warehouses than
 * half the width can carry does the grid overflow, and then it scrolls
 * horizontally — the size column staying put.
 *
 * Both days render the SAME warehouse columns (the union, fullest first across
 * the pair) and the same size rows, so a row reads straight across: the same
 * size at the same warehouse, yesterday then today.
 *
 * Native `<table>`, same reasoning as MetricsTable.vue: fixed column order, no
 * sorting and no pagination, so PrimeVue's machinery would add only overhead.
 */
const props = defineProps({
  /**
   * The days to compare, oldest first.
   * @type {Array<{key: string, label: string, loading: boolean, cells: object[]}>}
   */
  days: { type: Array, required: true },
  /**
   * The shared row set (`[{chrt_id, tech_size}]`) — the union of every day's
   * sizes, so a size missing from one day renders as a blank cell there.
   */
  sizeOrder: { type: Array, default: () => [] },
  /** Message when not one of the days has any stock at all. */
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

/** The warehouse columns every day repeats — the union, fullest pair-wise first. */
const warehouses = computed(() => sharedWarehouses(props.days.map((day) => day.cells)))

/** Per day: its rows (in the shared order), its per-warehouse and grand totals. */
const columns = computed(() =>
  props.days.map((day) => {
    const rows = pivotRows(day.cells, props.sizeOrder, sizeLabel)
    const totals = {}
    for (const row of rows) {
      for (const [name, quantity] of Object.entries(row.quantities)) {
        totals[name] = (totals[name] ?? 0) + quantity
      }
    }
    const grandTotal = rows.reduce((sum, row) => sum + row.total, 0)
    return { ...day, rows, totals, grandTotal }
  }),
)

const hasStock = computed(() => warehouses.value.length > 0)
</script>

<template>
  <div
    class="app-datatable"
    :style="{ '--day-warehouses': warehouses.length, '--days': days.length }"
  >
    <div v-if="!hasStock" class="px-md py-xl text-center text-base text-muted">
      {{ emptyMessage }}
    </div>

    <div v-else v-drag-scroll class="stock-scroll">
      <table>
        <thead>
          <!-- Row 1: one label spanning each day's whole group. -->
          <tr>
            <th class="col-size" rowspan="2">Размер</th>
            <th
              v-for="day in columns"
              :key="day.key"
              class="col-day day-start"
              :colspan="warehouses.length + 1"
            >
              {{ day.label }}
              <span v-if="!day.cells.length" class="text-muted">· нет снимка</span>
            </th>
          </tr>
          <!-- Row 2: that day's «Всего», then the shared warehouse columns. -->
          <tr>
            <template v-for="day in columns" :key="day.key">
              <th class="col-total day-start">Всего</th>
              <th
                v-for="wh in warehouses"
                :key="`${day.key}:${wh}`"
                class="col-wh"
                @mouseenter="showNameTip($event, wh)"
                @mouseleave="hideNameTip"
              >
                {{ shortWarehouseName(wh) }}
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
                :class="day.loading ? 'is-loading' : ''"
                :style="{ '--share': sizeShare(day.rows[index]?.total, day.grandTotal) }"
              >
                {{ day.rows[index]?.total ? formatNumber(day.rows[index].total) : '' }}
              </td>
              <td
                v-for="wh in warehouses"
                :key="`${day.key}:${wh}`"
                class="tabular-nums"
                :class="day.loading ? 'is-loading' : ''"
              >
                <!-- Zeros read as blanks — only real remainders carry a number. -->
                <span v-if="day.rows[index]?.quantities[wh]">{{
                  formatNumber(day.rows[index].quantities[wh])
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
                v-for="wh in warehouses"
                :key="`${day.key}:${wh}`"
                class="font-semibold tabular-nums"
              >
                {{ day.totals[wh] ? formatNumber(day.totals[wh]) : '' }}
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
