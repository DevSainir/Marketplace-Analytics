<script setup>
/**
 * The metric rows of the table — the grid the page exists to show.
 *
 * One row per metric, laid out over the column model for the current days.
 * Editable cells (per the backend's editability map) turn into an input on
 * click; committing (Enter/blur) emits `edit` with the raw numeric value, and
 * the backend recomputes every dependent cell. Read-only cells render as plain
 * text.
 *
 * Carts/orders cells additionally carry a `data-assoc` key: the parent runs ONE
 * delegated mouseover listener over the whole grid rather than a listener per
 * cell, because there are thousands of them.
 *
 * Renders a `<tbody>`: a section of the parent's single `<table>`, which is
 * what keeps its day columns aligned with every other row section.
 */
import { useCellEditing, vFocus } from '@/modules/labs/useCellEditing'

const props = defineProps({
  /** @type {Array<{key, label, tone, cells: object[]}>} day-major cell objects */
  rows: { type: Array, required: true },
  /** The column set each row renders over (merged for the two spanning rows). */
  rowColumns: { type: Function, required: true },
  /** `data-assoc` key for a cell, or null when it has no breakdown. */
  assocData: { type: Function, required: true },
  /** Disable editing while a save/refresh is in flight. */
  editingDisabled: { type: Boolean, default: false },
})

const emit = defineEmits(['edit'])

const { editingId, draft, startEdit, commitEdit, cancelEdit } = useCellEditing({
  disabled: () => props.editingDisabled,
  onCommit: (payload) => emit('edit', payload),
})

// Metric accents: «Затраты» green, «Заказы»/«Конверсия в заказ» amber,
// «Корзины»/«Конверсия в корзину» indigo. Labels always; cells only when filled.
const TONE_CLASSES = {
  warning: 'text-status-warning',
  negative: 'text-status-negative',
  positive: 'text-status-positive',
  carts: 'text-accent-indigo',
}

function cellToneClass(row, cell) {
  if (!row.tone || cell.raw == null) return 'text-primary'
  return TONE_CLASSES[row.tone]
}

// Each metric row belongs to one of four data blocks (traffic / funnel /
// money / efficiency); the block reads through a subtle row tint (see the
// `matrix-group--*` rules in main.css). «ДРР от продаж» is emphasized.
function rowClasses(row) {
  return [
    row.group && `matrix-group--${row.group}`,
    row.emphasis && 'matrix-row-emphasis',
    // A merged row lays out fewer cells per day than the skin's per-leaf
    // border cadence in main.css assumes, so each restates its own boundaries
    // below: «ДРР от продаж» has one per traffic group, «Процент выкупа»
    // exactly one per day.
    row.key === 'drr_sales' && 'matrix-row-merged matrix-row-merged--campaign',
    row.key === 'buyout_percent' && 'matrix-row-merged matrix-row-merged--day',
  ]
}
</script>

<template>
  <tbody class="matrix-metrics">
    <tr v-for="row in rows" :key="row.key" :class="rowClasses(row)">
      <td>
        <span class="matrix-row-label" :class="row.tone ? TONE_CLASSES[row.tone] : 'text-primary'">
          {{ row.label }}
        </span>
      </td>
      <td
        v-for="leaf in rowColumns(row)"
        :key="leaf.id"
        :colspan="leaf.colspan ?? 1"
        :class="(leaf.span ?? 1) > 1 && 'matrix-cell--merged'"
      >
        <template v-if="row.cells[leaf.index]">
          <input
            v-if="editingId === `${row.cells[leaf.index].day}:${leaf.key}:${row.key}`"
            v-model="draft"
            v-focus
            type="text"
            inputmode="decimal"
            class="matrix-cell-input"
            @keydown.enter.prevent="commitEdit(row, row.cells[leaf.index])"
            @keydown.esc.prevent="cancelEdit"
            @blur="commitEdit(row, row.cells[leaf.index])"
          />
          <button
            v-else-if="row.cells[leaf.index].editable && !editingDisabled"
            type="button"
            class="matrix-cell-btn tabular-nums font-medium"
            :class="cellToneClass(row, row.cells[leaf.index])"
            :data-assoc="assocData(row, row.cells[leaf.index])"
            @click="startEdit(row, row.cells[leaf.index])"
          >
            {{ row.cells[leaf.index].display }}
          </button>
          <span
            v-else
            class="tabular-nums font-medium"
            :class="cellToneClass(row, row.cells[leaf.index])"
            :data-assoc="assocData(row, row.cells[leaf.index])"
          >
            {{ row.cells[leaf.index].display }}
          </span>
        </template>
      </td>
    </tr>
  </tbody>
</template>

<style scoped src="./styles/MatrixMetricsRows.css"></style>
