<script setup>
/**
 * The day-bound «Цены» / «Остатки» blocks under the metric rows.
 *
 * Per day section, one tight label+value card per family that fits inside its
 * day's width and scrolls WITH the day — same table, same scroll container, no
 * sync needed. Both are «Общая»-bucket only: neither price nor stock has a
 * per-zone meaning.
 *
 * Prices are editable (a seller price is a fact we can correct); stock is
 * read-only (it is a snapshot of what WB reported). Editing reuses the shared
 * `useCellEditing` composable so a price cell behaves exactly like a metric
 * cell above it.
 *
 * Renders a `<tbody>`: a section of the parent's single `<table>`.
 */
import { computed } from 'vue'

import { DAY_COLSPAN } from '@/modules/monitoring/metricsMatrix'

import MatrixFigure from '@/modules/monitoring/components/MatrixFigure.vue'
import { useCellEditing, vFocus } from '@/modules/monitoring/useCellEditing'

const props = defineProps({
  /** @type {Array<{iso: string, label: string}>} oldest -> newest */
  days: { type: Array, required: true },
  /** «Цены» block rows — one «Общая» cell per day (prices editable). */
  priceRows: { type: Array, default: () => [] },
  /** «Остатки» block rows — one «Общая» cell per day (read-only). */
  stockRows: { type: Array, default: () => [] },
  /** «Всего» card row — per-day total stock (остаток + оба «в пути»), read-only. */
  stockTotalRows: { type: Array, default: () => [] },
  /** Disable editing while a save/refresh is in flight. */
  editingDisabled: { type: Boolean, default: false },
})

const emit = defineEmits(['edit'])

const { editingId, draft, cellId, startEdit, commitEdit, cancelEdit } = useCellEditing({
  disabled: () => props.editingDisabled,
  onCommit: (payload) => emit('edit', payload),
})

const blocks = computed(() => [
  { key: 'prices', title: 'Цены', titleClass: 'text-action', rows: props.priceRows },
  { key: 'stock', title: 'Остатки', titleClass: 'text-accent-indigo', rows: props.stockRows },
])
</script>

<template>
  <tbody v-if="priceRows.length || stockRows.length" class="matrix-blocks">
    <tr class="matrix-gap" aria-hidden="true">
      <td :colspan="1 + days.length * DAY_COLSPAN"></td>
    </tr>
    <tr>
      <td>
        <span class="text-micro font-semibold uppercase tracking-wide">
          <span class="text-action">Цены</span><span class="text-muted">/</span
          ><span class="text-accent-indigo">Остатки</span>
        </span>
      </td>
      <td v-for="(day, dayIndex) in days" :key="day.iso" :colspan="DAY_COLSPAN">
        <div class="day-block-pair">
          <div
            v-for="block in blocks"
            :key="block.key"
            class="day-block"
            :class="`day-block--${block.key}`"
          >
            <div v-for="row in block.rows" :key="row.key" class="day-block-line">
              <span class="day-block-name">{{ row.label }}</span>
              <template v-if="row.cells[dayIndex]">
                <input
                  v-if="editingId === cellId(row.key, row.cells[dayIndex])"
                  v-model="draft"
                  v-focus
                  type="text"
                  inputmode="decimal"
                  class="matrix-cell-input day-block-input"
                  @keydown.enter.prevent="commitEdit(row, row.cells[dayIndex])"
                  @keydown.esc.prevent="cancelEdit"
                  @blur="commitEdit(row, row.cells[dayIndex])"
                />
                <button
                  v-else-if="row.cells[dayIndex].editable && !editingDisabled"
                  type="button"
                  class="matrix-cell-btn day-block-value tabular-nums"
                  @click="startEdit(row, row.cells[dayIndex])"
                >
                  <MatrixFigure :cell="row.cells[dayIndex]" />
                </button>
                <span v-else class="day-block-value tabular-nums">
                  <MatrixFigure :cell="row.cells[dayIndex]" />
                </span>
              </template>
            </div>
          </div>

          <!-- Compact «Всего» card: total stock (остаток + оба «в пути»)
               for the day. Same tint as «Остатки» — it belongs to it. -->
          <div v-if="stockTotalRows.length" class="day-block day-block--stock day-block--total">
            <span class="day-block-name">Всего, шт</span>
            <span class="day-block-total-value tabular-nums">
              {{ stockTotalRows[0].cells[dayIndex]?.display ?? '' }}
            </span>
          </div>
        </div>
      </td>
    </tr>
  </tbody>
</template>

<style scoped src="./styles/MatrixDayBlocksRow.css"></style>
