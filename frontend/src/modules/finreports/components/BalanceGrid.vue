<script setup>
/**
 * Block 1 of the balance layout: the grid itself — SKU rows x warehouse columns.
 *
 * The only block that scrolls on both axes; the three totals blocks are driven
 * from its scroll position by the parent. Its article column is sticky inside
 * it, so a row never loses its name while the warehouses scroll past.
 *
 * The trailing spacer column is what makes the grid fill the block instead of
 * the warehouse columns stretching: they stay one fixed width whether there are
 * three warehouses or thirty, and the zebra and rules still reach the far edge.
 */
import { ref } from 'vue'

import { NAME_LIMIT, shortWarehouseName } from '@/modules/finreports/useBalanceRows'

import { vDragScroll } from '@/core/utils/dragScroll'
import { formatNumber } from '@/core/utils/format'

defineProps({
  /** `[{name, isPinned, isUncounted, stock}]`, in display order. */
  columns: { type: Array, required: true },
  /** Flattened rows, in display order. */
  rows: { type: Array, required: true },
  /** Money formatter bound to the response currency. */
  money: { type: Function, required: true },
  pinnedCount: { type: Number, default: 0 },
  uncountedCount: { type: Number, default: 0 },
  ordinaryCount: { type: Number, default: 0 },
  /** `(index) => boolean` — true on the first column of a new group. */
  isGroupBoundary: { type: Function, required: true },
  /** `(index) => boolean` — true on the first row after the pinned ones. */
  isRowBoundary: { type: Function, required: true },
})

const emit = defineEmits(['open-menu', 'show-tip', 'hide-tip'])

const scroller = ref(null)
defineExpose({ scroller })
</script>

<template>
  <div ref="scroller" v-drag-scroll class="balance-block grid-scroll">
    <table>
      <!-- `table-layout: fixed` reads its widths from the first row, and the
           first row here is all colspans — so the columns declare themselves.
           BalanceColumnTotals repeats this list; the two must stay identical or
           the totals slide out from under their warehouses. -->
      <colgroup>
        <col class="c-sku" />
        <col v-for="column in columns" :key="column.name" class="c-wh" />
        <col class="c-spacer" />
      </colgroup>
      <thead>
        <tr>
          <th rowspan="2" class="col-sku">Артикул</th>
          <th v-if="pinnedCount" :colspan="pinnedCount" class="wh-group wh-group--pinned">
            <span class="wh-group-label">Закреплено</span>
          </th>
          <th
            v-if="ordinaryCount > 0"
            :colspan="ordinaryCount"
            class="wh-group"
            :class="{ 'wh-divide': pinnedCount > 0 }"
          >
            <span class="wh-group-label">Склады</span>
          </th>
          <th
            v-if="uncountedCount"
            :colspan="uncountedCount"
            class="wh-group wh-group--uncounted"
            :class="{ 'wh-divide': columns.length > uncountedCount }"
          >
            <span class="wh-group-label">Не считается</span>
          </th>
          <th rowspan="2" class="col-spacer"></th>
        </tr>
        <tr>
          <th
            v-for="(column, index) in columns"
            :key="column.name"
            class="col-wh"
            :class="{ 'wh-divide': isGroupBoundary(index), 'is-uncounted': column.isUncounted }"
            @mouseenter="emit('show-tip', { event: $event, name: column.name, limit: NAME_LIMIT })"
            @mouseleave="emit('hide-tip')"
          >
            <span class="wh-header">
              <span :class="{ 'is-pinned': column.isPinned }">
                {{ shortWarehouseName(column.name) }}
              </span>
              <button
                type="button"
                class="pin-menu-btn"
                :aria-label="`Действия со складом ${column.name}`"
                @click="
                  emit('open-menu', {
                    event: $event,
                    target: {
                      kind: 'warehouse',
                      value: column.name,
                      label: column.name,
                      pinned: column.isPinned,
                      uncounted: column.isUncounted,
                    },
                  })
                "
              >
                ⋮
              </button>
            </span>
          </th>
        </tr>
      </thead>

      <tbody>
        <tr
          v-for="(row, rowIndex) in rows"
          :key="row.nmId"
          :class="{ 'row-divide': isRowBoundary(rowIndex), 'is-uncounted': row.isUncounted }"
        >
          <td class="cell-sku" :title="row.saName">
            <span class="sku-header">
              <button
                type="button"
                class="pin-menu-btn"
                :aria-label="`Действия с артикулом ${row.saName}`"
                @click="
                  emit('open-menu', {
                    event: $event,
                    target: {
                      kind: 'sku',
                      value: String(row.nmId),
                      label: row.saName,
                      pinned: row.isPinned,
                      uncounted: row.isUncounted,
                    },
                  })
                "
              >
                ⋮
              </button>
              <span class="sku-name" :class="{ 'is-pinned': row.isPinned }">{{ row.saName }}</span>
            </span>
          </td>
          <td
            v-for="(column, index) in columns"
            :key="column.name"
            class="cell-wh tabular-nums"
            :class="{ 'wh-divide': isGroupBoundary(index), 'is-uncounted': column.isUncounted }"
          >
            <!-- Zeros read as blanks — only real remainders carry figures. The
                 divider sits on the column's centre line, stock closing on it
                 from the left and money opening from the right, so a column
                 reads as two aligned числа rather than one ragged string.
                 Both figures are what is LYING here: goods in transit belong to
                 no shelf and are reported once, in «Итого по артикулу». -->
            <div v-if="row.byWarehouse[column.name]" class="cell-split">
              <span class="cell-stock">
                {{ formatNumber(row.byWarehouse[column.name].quantity) }}
              </span>
              <span class="cell-sep">|</span>
              <span class="cell-money">{{ money(row.byWarehouse[column.name].balance) }}</span>
            </div>
          </td>
          <td class="col-spacer"></td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped src="./styles/BalanceGrid.css"></style>
