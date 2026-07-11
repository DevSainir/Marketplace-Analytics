<script setup>
/**
 * Day-by-day metrics table (spreadsheet-like): a horizontal ribbon of day
 * sections, each one the workbook's 7-column «тип трафика × зона показов»
 * block, newest day on the right. Auto-scrolls to the newest day whenever a
 * new matrix arrives; the metric-name column stays frozen on the left while
 * scrolling (see `.app-datatable--matrix` skin in main.css).
 *
 * Editable cells (per the backend editability map) turn into an input on
 * click; committing (Enter/blur) emits `edit` with the raw numeric value —
 * the parent sends it to the backend, which recomputes dependents. Read-only
 * cells render as plain text.
 *
 * Header (3 rows, as in the workbook):
 *   Дата · Тип получения трафика (groups) · Зоны показов (leaf columns).
 */
import Column from 'primevue/column'
import ColumnGroup from 'primevue/columngroup'
import DataTable from 'primevue/datatable'
import Row from 'primevue/row'
import { computed, nextTick, onMounted, ref, watch } from 'vue'

import { TRAFFIC_COLUMNS, TRAFFIC_GROUPS } from '@/modules/monitoring/metricsMatrix'

const props = defineProps({
  /** @type {Array<{iso: string, label: string}>} oldest → newest */
  days: { type: Array, required: true },
  /** @type {Array<{key, label, tone, cells: object[]}>} day-major cell objects */
  rows: { type: Array, required: true },
  /** Disable editing while a save/refresh is in flight. */
  editingDisabled: { type: Boolean, default: false },
})

const emit = defineEmits(['edit'])

// One leaf column per day × traffic column; `index` addresses row.cells.
const leafColumns = computed(() =>
  props.days.flatMap((day, dayIndex) =>
    TRAFFIC_COLUMNS.map((column, columnIndex) => ({
      id: `${day.iso}:${column.key}`,
      key: column.key,
      zone: column.zone,
      index: dayIndex * TRAFFIC_COLUMNS.length + columnIndex,
    })),
  ),
)

// «Общая»/«Органика» cells span the zones row (rowspan=2 in the type row),
// so the zones row only lists the columns that actually have a zone split.
const zonedGroupKeys = new Set([
  'uni_search',
  'uni_shelves',
  'uni_catalog',
  'manual_search',
  'manual_shelves',
])
const zoneHeaderColumns = computed(() =>
  leafColumns.value.filter((leaf) => zonedGroupKeys.has(leaf.key)),
)

// Metric accents: «Затраты» warning, «Заказы»/«Конверсия в заказ» positive,
// «Корзины»/«Конверсия в корзину» indigo. Labels always; cells only when filled.
const TONE_CLASSES = {
  warning: 'text-status-warning',
  positive: 'text-status-positive',
  carts: 'text-accent-indigo',
}

function cellToneClass(row, cell) {
  if (!row.tone || cell.display === '—') return 'text-primary'
  return TONE_CLASSES[row.tone]
}

// --- inline editing -----------------------------------------------------
// The cell currently being edited, addressed by its stable id, plus the draft.
const editingId = ref(null)
const draft = ref('')

function cellId(row, cell) {
  return `${cell.day}:${cell.bucket}:${row.key}`
}

function startEdit(row, cell) {
  if (props.editingDisabled || !cell.editable) return
  editingId.value = cellId(row, cell)
  draft.value = cell.raw == null ? '' : String(cell.raw)
}

function commitEdit(row, cell) {
  if (editingId.value !== cellId(row, cell)) return
  const raw = draft.value.trim().replace(',', '.')
  const value = Number(raw)
  editingId.value = null
  // Ignore empty/invalid input or a no-op (unchanged value).
  if (raw === '' || Number.isNaN(value) || value === cell.raw) return
  emit('edit', { day: cell.day, bucket: cell.bucket, metric: cell.metric, value })
}

function cancelEdit() {
  editingId.value = null
}

// Focus (and select) the inline input the moment it appears, so typing lands in
// it and — crucially — clicking anywhere outside blurs it, committing + closing
// (a plain `autofocus` attribute does nothing on a dynamically inserted node).
const vFocus = {
  mounted(el) {
    el.focus()
    el.select()
  },
}

const root = ref(null)

/** Start at the right edge: «сегодня» first, older days appear as you scroll left. */
function scrollToNewestDay() {
  const container = root.value?.querySelector("[data-pc-section='tablecontainer']")
  if (container) container.scrollLeft = container.scrollWidth
}

onMounted(scrollToNewestDay)
watch(
  () => props.days,
  () => nextTick(scrollToNewestDay),
)
</script>

<template>
  <!-- --matrix-days drives the fixed-layout width so EXACTLY two day
       sections fill the viewport (see .app-datatable--matrix in main.css). -->
  <div
    ref="root"
    class="app-datatable app-datatable--matrix"
    :style="`--matrix-days: ${days.length}`"
  >
    <DataTable :value="rows" data-key="key">
      <template #empty>
        <div class="px-md py-xl text-center text-base text-muted">
          Нет данных за выбранный период.
        </div>
      </template>

      <ColumnGroup type="header">
        <Row>
          <Column header="Дата" />
          <Column v-for="day in days" :key="day.iso" :header="day.label" :colspan="7" />
        </Row>
        <Row>
          <Column header="Тип получения трафика" />
          <template v-for="day in days" :key="day.iso">
            <Column
              v-for="group in TRAFFIC_GROUPS"
              :key="`${day.iso}:${group.label}`"
              :header="group.label"
              :colspan="group.span"
              :rowspan="group.spansZones ? 2 : 1"
            />
          </template>
        </Row>
        <Row>
          <Column header="Зоны показов" />
          <Column v-for="leaf in zoneHeaderColumns" :key="leaf.id" :header="leaf.zone" />
        </Row>
      </ColumnGroup>

      <Column field="label">
        <template #body="{ data }">
          <span
            class="font-medium"
            :class="data.tone ? TONE_CLASSES[data.tone] : 'text-primary'"
          >
            {{ data.label }}
          </span>
        </template>
      </Column>

      <Column v-for="leaf in leafColumns" :key="leaf.id">
        <template #body="{ data }">
          <template v-if="data.cells[leaf.index]">
            <input
              v-if="editingId === `${data.cells[leaf.index].day}:${leaf.key}:${data.key}`"
              v-model="draft"
              v-focus
              type="text"
              inputmode="decimal"
              class="matrix-cell-input"
              @keydown.enter.prevent="commitEdit(data, data.cells[leaf.index])"
              @keydown.esc.prevent="cancelEdit"
              @blur="commitEdit(data, data.cells[leaf.index])"
            />
            <button
              v-else-if="data.cells[leaf.index].editable && !editingDisabled"
              type="button"
              class="matrix-cell-btn tabular-nums font-medium"
              :class="cellToneClass(data, data.cells[leaf.index])"
              @click="startEdit(data, data.cells[leaf.index])"
            >
              {{ data.cells[leaf.index].display }}
            </button>
            <span
              v-else
              class="tabular-nums font-medium"
              :class="cellToneClass(data, data.cells[leaf.index])"
            >
              {{ data.cells[leaf.index].display }}
            </span>
          </template>
        </template>
      </Column>
    </DataTable>
  </div>
</template>

<style scoped>
/* An editable cell reads as plain text but hints affordance on hover/focus. */
.matrix-cell-btn {
  display: inline-block;
  width: 100%;
  padding: 0;
  border: none;
  background: transparent;
  text-align: inherit;
  /* Inherit family/size but keep the medium weight (a `font` shorthand would
     reset weight back to the inherited 400). */
  font-family: inherit;
  font-size: inherit;
  font-weight: 500;
  cursor: text;
  border-bottom: 1px dashed transparent;
}
.matrix-cell-btn:hover,
.matrix-cell-btn:focus-visible {
  border-bottom-color: currentColor;
  outline: none;
}

.matrix-cell-input {
  width: 100%;
  min-width: 3.5rem;
  padding: 2px 4px;
  border: 1px solid var(--color-action, #2f7d68);
  border-radius: 4px;
  background: var(--color-surface, #fff);
  color: inherit;
  font: inherit;
  font-weight: 500;
  text-align: inherit;
  font-variant-numeric: tabular-nums;
}
.matrix-cell-input:focus {
  outline: 2px solid color-mix(in srgb, var(--color-action, #2f7d68) 40%, transparent);
  outline-offset: 0;
}
</style>
