<script setup>
/**
 * Block 2: «Итого по артикулу» — one row per SKU, beside the grid.
 *
 * A table of its own, not a frozen column of the grid: it never scrolls
 * sideways, so the three totals stay put however far the warehouses run. Its
 * rows are the grid's rows in the same order and at the same height, and the
 * parent drives its vertical scroll from the grid's — which is what keeps the
 * two aligned to the pixel.
 *
 * «В пути» sits between the units and the money because it belongs to both: the
 * goods riding to a buyer (or back from one) are not part of «По остаткам» —
 * they cannot be shipped today — but they ARE part of «По себестоимости», money
 * the seller has already spent and will get back one way or the other.
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
        <col class="c-way" />
        <col class="c-cost" />
      </colgroup>
      <thead>
        <tr>
          <th colspan="3" class="panel-title">Итого по артикулу</th>
        </tr>
        <tr>
          <th class="col-qty">По остаткам</th>
          <th class="col-way" title="К клиенту и от клиента">В пути</th>
          <th class="col-cost">По себестоимости</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="(row, rowIndex) in rows"
          :key="row.nmId"
          :class="{ 'row-divide': isRowBoundary(rowIndex), 'is-uncounted': row.isUncounted }"
        >
          <td class="col-qty tabular-nums">{{ formatNumber(row.totalQuantity) }}</td>
          <!-- Nothing in motion is a blank, not a zero: a column of «0» down a
               catalogue that mostly sits still buries the few rows that move. -->
          <td class="col-way tabular-nums">
            {{ row.totalInWay ? formatNumber(row.totalInWay) : '' }}
          </td>
          <td class="col-cost tabular-nums">{{ money(row.totalBalance) }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped src="./styles/BalanceRowTotals.css"></style>
