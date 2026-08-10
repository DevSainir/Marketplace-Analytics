<script setup>
/**
 * Block 2: «Итого по артикулу» — one row per SKU, beside the grid.
 *
 * A table of its own, not a frozen column of the grid: it never scrolls
 * sideways, so the two totals stay put however far the warehouses run. Its rows
 * are the grid's rows in the same order and at the same height, and the parent
 * drives its vertical scroll from the grid's — which is what keeps the two
 * aligned to the pixel.
 */
import { ref } from 'vue'

import { formatNumber } from '@/core/utils/format'

defineProps({
  /** Flattened rows, in the grid's display order. */
  rows: { type: Array, required: true },
  /** Money formatter bound to the response currency. */
  money: { type: Function, required: true },
  /** `(index) => boolean` — true on the first row after the pinned ones. */
  isRowBoundary: { type: Function, required: true },
})

const scroller = ref(null)
defineExpose({ scroller })
</script>

<template>
  <div ref="scroller" class="balance-block totals-scroll">
    <table>
      <!-- `table-layout: fixed` reads its widths from the first row, which is
           the block's title spanning both columns — so they declare themselves. -->
      <colgroup>
        <col class="c-qty" />
        <col class="c-cost" />
      </colgroup>
      <thead>
        <tr>
          <th colspan="2" class="panel-title">Итого по артикулу</th>
        </tr>
        <tr>
          <th class="col-qty">По остаткам</th>
          <th class="col-cost">По себестоимости</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="(row, rowIndex) in rows"
          :key="row.nmId"
          :class="{ 'row-divide': isRowBoundary(rowIndex) }"
        >
          <td class="col-qty tabular-nums">{{ formatNumber(row.totalQuantity) }}</td>
          <td class="col-cost tabular-nums">{{ money(row.totalBalance) }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped src="./styles/BalanceRowTotals.css"></style>
