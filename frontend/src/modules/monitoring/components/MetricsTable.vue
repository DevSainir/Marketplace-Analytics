<script setup>
/**
 * Day-by-day metrics table (spreadsheet-like): a horizontal ribbon of day
 * sections, each one the workbook's 7-column «тип трафика × зона показов»
 * block, newest day on the right. Auto-scrolls to the newest day whenever a
 * new matrix arrives; the metric-name column stays frozen on the left while
 * scrolling (see `.app-datatable--matrix` skin in main.css).
 *
 * Rendered as a NATIVE `<table>` (not PrimeVue DataTable): the matrix is
 * ~4400 cells and PrimeVue's per-column component overhead made the initial
 * render ~1.6s; a plain table paints the same grid in ~300ms. The styling is
 * DOM-generic (`table`/`thead th`/`tbody td`), so it carries over unchanged;
 * only the scroll container moved from PrimeVue's `[data-pc-section=
 * 'tablecontainer']` to `.matrix-scroll`.
 *
 * Below the metric rows, two compact DAY-BOUND blocks render per day section
 * («Цены» / «Остатки», «Общая»-bucket only): one tight label+value card that
 * fits inside its day's width and scrolls WITH the day — same table, same
 * scroll container, no sync needed.
 *
 * Editable cells (per the backend editability map) turn into an input on
 * click; committing (Enter/blur) emits `edit` with the raw numeric value —
 * the parent sends it to the backend, which recomputes dependents. Read-only
 * cells render as plain text.
 *
 * Header (3 rows, as in the workbook):
 *   Дата · Тип получения трафика (groups) · Зоны показов (leaf columns).
 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'

import { TRAFFIC_COLUMNS, TRAFFIC_GROUPS } from '@/modules/monitoring/metricsMatrix'

const props = defineProps({
  /** @type {Array<{iso: string, label: string}>} oldest → newest */
  days: { type: Array, required: true },
  /** @type {Array<{key, label, tone, cells: object[]}>} day-major cell objects */
  rows: { type: Array, required: true },
  /** «Цены» block rows — one «Общая» cell per day (prices editable). */
  priceRows: { type: Array, default: () => [] },
  /** «Остатки» block rows — one «Общая» cell per day (read-only). */
  stockRows: { type: Array, default: () => [] },
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

// Metric accents: «Затраты» negative, «Заказы»/«Конверсия в заказ» positive,
// «Корзины»/«Конверсия в корзину» indigo. Labels always; cells only when filled.
const TONE_CLASSES = {
  warning: 'text-status-warning',
  negative: 'text-status-negative',
  positive: 'text-status-positive',
  carts: 'text-accent-indigo',
}

function cellToneClass(row, cell) {
  if (!row.tone || cell.display === '—') return 'text-primary'
  return TONE_CLASSES[row.tone]
}

// Metric groups («Заказы, ₽»..«Стоимость корзины», «ДРР»..«Процент выкупа»)
// are separated by a thick divider above their first row — separation only.
function rowClasses(row, index) {
  if (!row.group) return null
  return [
    'matrix-group-row',
    props.rows[index - 1]?.group !== row.group && 'matrix-group-start',
  ]
}

// The two day-bound blocks under the metric rows.
const blocks = computed(() => [
  { key: 'prices', title: 'Цены', titleClass: 'text-action', rows: props.priceRows },
  { key: 'stock', title: 'Остатки', titleClass: 'text-accent-indigo', rows: props.stockRows },
])

// --- inline editing -----------------------------------------------------
// The cell currently being edited, addressed by its stable id, plus the draft.
const editingId = ref(null)
const draft = ref('')

function cellId(rowKey, cell) {
  return `${cell.day}:${cell.bucket}:${rowKey}`
}

function startEdit(row, cell) {
  if (props.editingDisabled || !cell.editable) return
  editingId.value = cellId(row.key, cell)
  draft.value = cell.raw == null ? '' : String(cell.raw)
}

function commitEdit(row, cell) {
  if (editingId.value !== cellId(row.key, cell)) return
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

const scroll = ref(null)

/** Start at the right edge: «сегодня» first, older days appear as you scroll left. */
function scrollToNewestDay() {
  const container = scroll.value
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
  <div class="app-datatable app-datatable--matrix" :style="`--matrix-days: ${days.length}`">
    <div v-if="!rows.length" class="px-md py-xl text-center text-base text-muted">
      Нет данных за выбранный период.
    </div>

    <div v-else ref="scroll" class="matrix-scroll">
      <table>
        <thead>
          <!-- Row 1: date, one label spanning each day's 7 columns. -->
          <tr>
            <th>Дата</th>
            <th v-for="day in days" :key="day.iso" :colspan="7">{{ day.label }}</th>
          </tr>
          <!-- Row 2: «Тип получения трафика» groups (Общая/Органика span row 3). -->
          <tr>
            <th>Тип получения трафика</th>
            <template v-for="day in days" :key="day.iso">
              <th
                v-for="group in TRAFFIC_GROUPS"
                :key="`${day.iso}:${group.label}`"
                :colspan="group.span"
                :rowspan="group.spansZones ? 2 : 1"
              >
                {{ group.label }}
              </th>
            </template>
          </tr>
          <!-- Row 3: «Зоны показов» — only the zoned leaf columns. -->
          <tr>
            <th>Зоны показов</th>
            <th v-for="leaf in zoneHeaderColumns" :key="leaf.id">{{ leaf.zone }}</th>
          </tr>
        </thead>

        <tbody class="matrix-metrics">
          <tr v-for="(row, rowIndex) in rows" :key="row.key" :class="rowClasses(row, rowIndex)">
            <td>
              <span
                class="matrix-row-label"
                :class="row.tone ? TONE_CLASSES[row.tone] : 'text-primary'"
              >
                {{ row.label }}
              </span>
            </td>
            <td v-for="leaf in leafColumns" :key="leaf.id">
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
                  @click="startEdit(row, row.cells[leaf.index])"
                >
                  {{ row.cells[leaf.index].display }}
                </button>
                <span
                  v-else
                  class="tabular-nums font-medium"
                  :class="cellToneClass(row, row.cells[leaf.index])"
                >
                  {{ row.cells[leaf.index].display }}
                </span>
              </template>
            </td>
          </tr>
        </tbody>

        <!-- Day-bound «Цены»/«Остатки» blocks: ONE row, each day cell holding
             the two tinted cards side by side, in the SAME table so they
             scroll with their day. -->
        <tbody v-if="priceRows.length || stockRows.length" class="matrix-blocks">
          <tr class="matrix-gap" aria-hidden="true">
            <td :colspan="1 + days.length * 7"></td>
          </tr>
          <tr>
            <td>
              <span class="text-micro font-semibold uppercase tracking-wide">
                <span class="text-action">Цены</span
                ><span class="text-muted">/</span
                ><span class="text-accent-indigo">Остатки</span>
              </span>
            </td>
            <td v-for="(day, dayIndex) in days" :key="day.iso" :colspan="7">
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
                        {{ row.cells[dayIndex].display }}
                      </button>
                      <span v-else class="day-block-value tabular-nums">
                        {{ row.cells[dayIndex].display }}
                      </span>
                    </template>
                  </div>
                </div>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
/* The native scroll container (replaces PrimeVue's tablecontainer). */
.matrix-scroll {
  max-height: none;
  overflow: auto;
}

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

/* --- metric emphasis -------------------------------------------------------
   The heavy `.app-datatable--matrix tbody...` prefixes out-rank the generic
   skin rules from main.css. */

/* Frozen row labels: a step bigger and bolder than the cell numbers. */
.app-datatable--matrix tbody.matrix-metrics td:first-child .matrix-row-label {
  font-size: 13px;
  font-weight: 600;
}

/* Metric groups: a thick divider above the group, roomier rows inside —
   the option-1 block feel without the tinting. */
.app-datatable--matrix tbody.matrix-metrics tr.matrix-group-row td {
  padding-top: 6px;
  padding-bottom: 6px;
}
.app-datatable--matrix tbody.matrix-metrics tr.matrix-group-start td {
  border-top: 3px solid #e0e0e0;
}

/* --- day-bound «Цены»/«Остатки» blocks ------------------------------------
   The heavy `.app-datatable--matrix tbody...` prefixes out-rank the skin's
   zebra/hover/day-border rules from main.css so the block area reads as open
   card space with one tinted card per day. */
.app-datatable--matrix tbody.matrix-blocks tr td {
  background: transparent;
  border-left: none;
  padding: 3px 6px;
  vertical-align: top;
}
.app-datatable--matrix tbody.matrix-blocks tr:hover td {
  background: transparent;
}
/* Section title cell: frozen with the rows, SOLID so it masks the cards
   scrolling underneath it. */
.app-datatable--matrix tbody.matrix-blocks tr td:first-child {
  background: #f1f1f1;
  padding: 9px 8px;
}
.app-datatable--matrix tbody.matrix-blocks tr:hover td:first-child {
  background: #f1f1f1;
}
/* Spacer rows: pure air between the metric grid and each block. */
.app-datatable--matrix tbody.matrix-blocks tr.matrix-gap td,
.app-datatable--matrix tbody.matrix-blocks tr.matrix-gap:hover td {
  background: transparent;
  border: none;
  height: 10px;
  padding: 0;
}

/* The two cards share one row: side by side, each taking half the day. */
.day-block-pair {
  display: flex;
  align-items: stretch;
  gap: 8px;
}

/* One tight card: label+value lines, half a day section wide. */
.day-block {
  display: flex;
  flex: 1;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
  padding: 6px 10px;
  border-radius: 10px;
}
.day-block--prices {
  background: rgba(0, 126, 118, 0.08);
}
.day-block--stock {
  background: rgba(79, 70, 229, 0.07);
}

.day-block-line {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}
.day-block-name {
  color: #667085;
  font-size: 11px;
  white-space: nowrap;
}
.day-block-value {
  font-weight: 500;
  color: #101010;
  text-align: right;
}
/* The generic cell button stretches to 100%; inside a block line it must only
   take its content so the label keeps the left edge. */
.day-block-line .matrix-cell-btn {
  width: auto;
}
.day-block-input {
  width: 6rem;
  text-align: right;
}
</style>
