<script setup>
/**
 * Block 3: "Warehouse total" — two rows under the grid, one column per warehouse.
 *
 * A table of its own, so it never scrolls out of sight vertically however long
 * the catalog is. Its columns mirror the grid's — same order, same widths,
 * same trailing spacer — and the parent drives its horizontal scroll from the
 * grid's, which is what keeps a column's total under that column.
 *
 * One figure per cell, centered: with no divider to hang them on, the two rows
 * read better on the column's own axis than pushed to an edge.
 *
 * Both rows describe the SHELF — what is lying at that warehouse. Goods in
 * transit have left one shelf and not reached another, so they are reported
 * once, in the two blocks that total the seller's whole holding: "SKU total"
 * and the corner. That is why the corner's money runs ahead of the
 * sum of this row, and "In transit" beside it is what accounts for the difference.
 *
 * A warehouse marked "Don't count" still shows its own figures here: the seller
 * wants to see what is lying there. It is the corner block that leaves it out.
 */
import { ref } from 'vue'

import { formatNumber } from '@/core/utils/format'

defineProps({
  /** `[{name, isUncounted, quantity, balance}]`, in display order. */
  warehouses: { type: Array, required: true },
  /** Money formatter bound to the response currency. */
  money: { type: Function, required: true },
  /** `(index) => boolean` — true on the first column of a new group. */
  isGroupBoundary: { type: Function, required: true },
})

const scroller = ref(null)
defineExpose({ scroller })
</script>

<template>
  <div ref="scroller" class="balance-block totals-scroll">
    <table>
      <!-- The grid's column list, repeated exactly: same order, same widths,
           same trailing spacer (see BalanceGrid.vue). -->
      <colgroup>
        <col class="c-sku" />
        <col v-for="column in warehouses" :key="column.name" class="c-wh" />
        <col class="c-spacer" />
      </colgroup>
      <tbody>
        <tr>
          <td class="cell-sku panel-title">Warehouse total, units</td>
          <td
            v-for="(column, index) in warehouses"
            :key="column.name"
            class="col-wh tabular-nums"
            :class="{ 'wh-divide': isGroupBoundary(index), 'is-uncounted': column.isUncounted }"
          >
            {{ column.quantity ? formatNumber(column.quantity) : '' }}
          </td>
          <td class="col-spacer"></td>
        </tr>
        <tr>
          <td class="cell-sku panel-title">Warehouse total, cost price</td>
          <td
            v-for="(column, index) in warehouses"
            :key="column.name"
            class="col-wh tabular-nums"
            :class="{ 'wh-divide': isGroupBoundary(index), 'is-uncounted': column.isUncounted }"
          >
            {{ column.balance ? money(column.balance) : '' }}
          </td>
          <td class="col-spacer"></td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped src="./styles/BalanceColumnTotals.css"></style>
