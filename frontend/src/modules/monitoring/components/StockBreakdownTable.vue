<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { formatNumber } from '@/core/utils/format'

/**
 * Warehouses × sizes stock matrix: a pivot of the backend `StockDetail.cells`
 * payload (latest snapshot day). Columns are warehouses ordered by their
 * total remaining stock — the fullest warehouse on the left; rows are the
 * SKU's sizes; each cell is the remaining quantity of that size at that
 * warehouse. A «Всего» column (frozen on the left, next to the size label)
 * and a «Всего» row carry the per-size / per-warehouse totals. Marked
 * warehouses group under an «Отгружено» title, the rest under «Неотгружено»,
 * with a vertical rule between the groups.
 *
 * Rendered as a native `<table>` inside the shared `.app-datatable` skin
 * (same approach as MetricsTable.vue): the column order is fixed by the
 * pivot rule and the row count is tiny, so PrimeVue's sortable-column and
 * pagination machinery add nothing here.
 */
const props = defineProps({
  /** `StockDetail.cells`: one entry per size (`chrt_id`) × warehouse. */
  cells: { type: Array, required: true },
  /**
   * Names of warehouses marked «на отгрузку»: underlined in the header and
   * always sorted ahead of unmarked ones (by stock among themselves).
   */
  markedWarehouses: { type: Array, default: () => [] },
})

const emit = defineEmits(['toggle-mark'])

const markedSet = computed(() => new Set(props.markedWarehouses))

/**
 * Human size label (WB «Размер вещи»); falls back to the raw `chrt_id`
 * until the content catalogue is synced for that size.
 */
function sizeLabel(row) {
  return row.tech_size ?? `chrt ${row.chrt_id}`
}

/**
 * Warehouses ordered by total remaining stock, fullest first (leftmost) —
 * except marked ones, which always come before every unmarked one and are
 * sorted by stock only among themselves.
 */
const warehouses = computed(() => {
  const totals = new Map()
  for (const cell of props.cells) {
    totals.set(cell.warehouse_name, (totals.get(cell.warehouse_name) ?? 0) + cell.quantity)
  }
  return [...totals]
    .map(([name, total]) => ({ name, total, marked: markedSet.value.has(name) }))
    .sort(
      (a, b) =>
        b.marked - a.marked || b.total - a.total || a.name.localeCompare(b.name, 'ru'),
    )
})

// --- warehouse mark menu --------------------------------------------------
// The ⋮ popup: rendered via Teleport with FIXED coordinates so the scroll
// container can't clip it. Only one menu at a time; any outside pointer-down,
// Esc, or any scroll closes it (scrolling would strand the fixed popup).
const menu = ref(null) // { name: string, x: number, y: number } | null

function openMenu(event, name) {
  if (menu.value?.name === name) {
    menu.value = null
    return
  }
  const rect = event.currentTarget.getBoundingClientRect()
  menu.value = { name, x: rect.left, y: rect.bottom + 4 }
}

function toggleMark() {
  emit('toggle-mark', menu.value.name)
  menu.value = null
}

function onDocumentPointerDown(event) {
  if (menu.value && !event.target.closest('.wh-menu, .wh-menu-btn')) menu.value = null
}
function onDocumentKeydown(event) {
  if (event.key === 'Escape') menu.value = null
}
function onAnyScroll() {
  menu.value = null
}

onMounted(() => {
  document.addEventListener('pointerdown', onDocumentPointerDown)
  document.addEventListener('keydown', onDocumentKeydown)
  document.addEventListener('scroll', onAnyScroll, true)
})
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onDocumentPointerDown)
  document.removeEventListener('keydown', onDocumentKeydown)
  document.removeEventListener('scroll', onAnyScroll, true)
})

/** One row per size: label + per-warehouse quantities + the row total. */
const rows = computed(() => {
  const byChrt = new Map()
  for (const cell of props.cells) {
    let row = byChrt.get(cell.chrt_id)
    if (!row) {
      row = { chrt_id: cell.chrt_id, tech_size: cell.tech_size, total: 0, quantities: {} }
      byChrt.set(cell.chrt_id, row)
    }
    row.quantities[cell.warehouse_name] =
      (row.quantities[cell.warehouse_name] ?? 0) + cell.quantity
    row.total += cell.quantity
  }
  // `numeric` keeps clothing sizes in wear order (42 < 44 < 122).
  return [...byChrt.values()].sort((a, b) =>
    sizeLabel(a).localeCompare(sizeLabel(b), 'ru', { numeric: true }),
  )
})

const grandTotal = computed(() => warehouses.value.reduce((sum, wh) => sum + wh.total, 0))

// Marked warehouses sort first, so the two header groups are contiguous:
// columns [0, markedCount) are «Отгружено», the rest «Неотгружено».
const markedCount = computed(() => warehouses.value.filter((wh) => wh.marked).length)

/** The vertical rule between the groups sits on the first unmarked column. */
function isGroupBoundary(index) {
  return markedCount.value > 0 && index === markedCount.value
}
</script>

<template>
  <div class="app-datatable">
    <div v-if="!cells.length" class="px-md py-xl text-center text-base text-muted">
      Нет складских остатков по этому SKU.
    </div>

    <div v-else class="stock-scroll">
      <table>
        <thead>
          <!-- Group titles: marked warehouses («Отгружено») first, the rest
               under «Неотгружено», with a vertical rule between the groups. -->
          <tr>
            <th rowspan="2" class="col-size">Размер</th>
            <th rowspan="2" class="col-total">Всего</th>
            <th v-if="markedCount" :colspan="markedCount" class="wh-group wh-group--marked">
              <span class="wh-group-label">Отгружено</span>
            </th>
            <th
              v-if="warehouses.length > markedCount"
              :colspan="warehouses.length - markedCount"
              class="wh-group"
              :class="{ 'wh-divide': markedCount > 0 }"
            >
              <span class="wh-group-label">Неотгружено</span>
            </th>
          </tr>
          <tr>
            <th
              v-for="(wh, whIndex) in warehouses"
              :key="wh.name"
              class="col-wh"
              :class="{ 'wh-divide': isGroupBoundary(whIndex) }"
            >
              <span class="wh-header">
                <span :class="{ 'wh-marked': wh.marked }">{{ wh.name }}</span>
                <button
                  type="button"
                  class="wh-menu-btn"
                  :aria-label="`Действия со складом ${wh.name}`"
                  @click="openMenu($event, wh.name)"
                >
                  ⋮
                </button>
              </span>
            </th>
          </tr>
        </thead>

        <tbody>
          <tr v-for="row in rows" :key="row.chrt_id">
            <td class="font-medium">{{ sizeLabel(row) }}</td>
            <td class="font-semibold tabular-nums">{{ formatNumber(row.total) }}</td>
            <td
              v-for="(wh, whIndex) in warehouses"
              :key="wh.name"
              class="tabular-nums"
              :class="{ 'wh-divide': isGroupBoundary(whIndex) }"
            >
              <span v-if="row.quantities[wh.name] === undefined" class="text-muted">—</span>
              <span v-else :class="row.quantities[wh.name] === 0 ? 'text-muted' : ''">
                {{ formatNumber(row.quantities[wh.name]) }}
              </span>
            </td>
          </tr>
        </tbody>

        <tfoot>
          <tr>
            <td class="font-medium">Всего</td>
            <td class="font-bold tabular-nums">{{ formatNumber(grandTotal) }}</td>
            <td
              v-for="(wh, whIndex) in warehouses"
              :key="wh.name"
              class="font-semibold tabular-nums"
              :class="{ 'wh-divide': isGroupBoundary(whIndex) }"
            >
              {{ formatNumber(wh.total) }}
            </td>
          </tr>
        </tfoot>
      </table>
    </div>

    <!-- The ⋮ mark menu: teleported so the scroll container can't clip it. -->
    <Teleport to="body">
      <div
        v-if="menu"
        class="wh-menu fixed z-50 rounded-card border border-border-subtle bg-surface p-sm shadow-card"
        :style="{ left: `${menu.x}px`, top: `${menu.y}px` }"
      >
        <label class="flex cursor-pointer select-none items-center gap-sm text-base text-primary">
          <input
            type="checkbox"
            class="wh-menu-checkbox"
            :checked="false"
            @change="toggleMark"
          />
          {{ markedSet.has(menu.name) ? 'Разгрузить' : 'Отгрузить' }}
        </label>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
/* Native scroll container: stands in for PrimeVue's `tablecontainer`, which
   the .app-datatable skin targets but native markup doesn't render. Scrolls
   only horizontally — every size row stays visible. The scrollbar is hidden
   entirely (macOS overlay scrollbars otherwise pin a white track over the
   table once hovered); scrolling still works via trackpad/wheel. */
.stock-scroll {
  overflow-x: auto;
  scrollbar-width: none;
}
.stock-scroll::-webkit-scrollbar {
  display: none;
}

/* Collapsed borders detach from sticky cells while scrolling — the frozen
   pane's right border would stay behind. Separate borders travel WITH the
   cell (same fix as the matrix table). */
table {
  border-collapse: separate;
  border-spacing: 0;
}

/* Warehouse header: name + the ⋮ mark-menu trigger. */
.wh-header {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.wh-menu-btn {
  padding: 0 2px;
  border: none;
  background: transparent;
  color: #858585;
  font-size: 13px;
  line-height: 1;
  cursor: pointer;
}
.wh-menu-btn:hover,
.wh-menu-btn:focus-visible {
  color: #101010;
  outline: none;
}
/* Marked («на отгрузку») warehouses carry the action-color underline. */
.wh-marked {
  text-decoration: underline;
  text-decoration-color: var(--color-action, #007e76);
  text-decoration-thickness: 2px;
  text-underline-offset: 4px;
}
.wh-menu-checkbox {
  accent-color: var(--color-action, #007e76);
}

/* Numbers right-align; their column headers follow (the skin's generic
   `thead th` is left-aligned). */
thead th.col-total,
thead th.col-wh,
tbody td:not(:first-child),
tfoot td:not(:first-child) {
  text-align: right;
}

/* Group titles («Отгружено» / «Неотгружено»). A group can span dozens of
   columns — far wider than the viewport — so the label sticks just right of
   the 16rem frozen pane and stays readable while the group scrolls by. The
   marked group carries the action color, echoing the name underline. */
thead th.wh-group {
  text-align: left;
}
thead th.wh-group .wh-group-label {
  position: sticky;
  left: calc(16rem + 12px);
  display: inline-block;
}
thead th.wh-group--marked {
  color: var(--color-action, #007e76);
}

/* The vertical rule between the marked and unmarked groups — same weight as
   the matrix table's day-section boundaries. */
.wh-divide {
  border-left: 3px solid #bcbcbc;
}

/* Frozen pane — the size label and its «Всего» total: sticky on the left
   with explicit backgrounds so they mask the warehouse columns scrolling
   underneath. The corner header cells span both header rows (rowspan=2),
   keep the skin's `sticky top-0` and additionally pin left. The size column
   is fixed-width so the totals column knows its offset. */
th.col-size,
td:first-child {
  width: 8rem;
  min-width: 8rem;
  max-width: 8rem;
}
thead th.col-size,
thead th.col-total {
  left: 0;
  z-index: 30;
  background: #f1f1f1;
}
tbody td:first-child,
tbody td:nth-child(2),
tfoot td:first-child,
tfoot td:nth-child(2) {
  position: sticky;
  left: 0;
  z-index: 20;
  background: #f1f1f1;
}
thead th.col-total,
tbody td:nth-child(2),
tfoot td:nth-child(2) {
  left: 8rem;
  border-right: 3px solid #e0e0e0;
}
/* The skin's row-hover tint sits on the transparent `<tr>`; the solid frozen
   cells would ignore it, so tint them explicitly (matching the skin's
   bg-canvas row hover). */
tbody tr:hover td:first-child,
tbody tr:hover td:nth-child(2) {
  background: #e8e8e8;
}

/* Totals row: pinned to the bottom edge, separated like the header. */
tfoot td {
  position: sticky;
  bottom: 0;
  border-top: 2px solid #e0e0e0;
  background: #f1f1f1;
  white-space: nowrap;
  padding: 8px 16px;
}
</style>
