<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { vDragScroll } from '@/core/utils/dragScroll'
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
  /**
   * Externally imposed row set/order (`[{chrt_id, tech_size}]`) — the two-day
   * comparison passes the UNION of both days' sizes so the side-by-side
   * tables share identical rows. A size absent from this day renders as an
   * all-blank row. `null` = derive rows from own cells (standalone mode).
   */
  sizeOrder: { type: Array, default: null },
  /**
   * Drop the own «Размер» column — the two-day comparison renders ONE shared
   * sizes panel (see StockSizesPanel.vue) to the left of both tables, so each
   * table only carries its day's «Всего» + warehouse columns.
   */
  hideSizeColumn: { type: Boolean, default: false },
  /** Message when the day has no cells at all. */
  emptyMessage: { type: String, default: 'Нет складских остатков по этому SKU.' },
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
 * Compact warehouse header: the first 8 letters (WB names like
 * «Электросталь» blow the columns up); the full name shows on hover via
 * the `title` attribute.
 */
function shortWarehouseName(name) {
  return name.length > 8 ? `${name.slice(0, 8)}…` : name
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
    .sort((a, b) => b.marked - a.marked || b.total - a.total || a.name.localeCompare(b.name, 'ru'))
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
  hoverTip.value = null
}

// --- warehouse name tooltip -------------------------------------------------
// Headers show only the first 8 letters; hovering a truncated header pops the
// full name. Teleported with FIXED coordinates (like the ⋮ menu) — an
// absolutely-positioned tip would be clipped by the scroll container.
const hoverTip = ref(null) // { name: string, x: number, y: number } | null

function showNameTip(event, name) {
  if (name.length <= 8) return // nothing truncated — nothing to reveal
  const rect = event.currentTarget.getBoundingClientRect()
  hoverTip.value = { name, x: rect.left, y: rect.bottom + 4 }
}

function hideNameTip() {
  hoverTip.value = null
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
    row.quantities[cell.warehouse_name] = (row.quantities[cell.warehouse_name] ?? 0) + cell.quantity
    row.total += cell.quantity
  }
  // Imposed row set (comparison mode): identical rows on both sides, a size
  // this day never stocked renders blank.
  if (props.sizeOrder) {
    return props.sizeOrder.map(
      (size) =>
        byChrt.get(size.chrt_id) ?? {
          chrt_id: size.chrt_id,
          tech_size: size.tech_size,
          total: 0,
          quantities: {},
        },
    )
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
  <div class="app-datatable" :class="{ 'stock-table--no-sizes': hideSizeColumn }">
    <div v-if="!cells.length" class="px-md py-xl text-center text-base text-muted">
      {{ emptyMessage }}
    </div>

    <div v-else v-drag-scroll class="stock-scroll">
      <table>
        <thead>
          <!-- Group titles: marked warehouses («Отгружено») first, the rest
               under «Неотгружено», with a vertical rule between the groups. -->
          <tr>
            <th v-if="!hideSizeColumn" rowspan="2" class="col-size">Размер</th>
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
              @mouseenter="showNameTip($event, wh.name)"
              @mouseleave="hideNameTip"
            >
              <span class="wh-header">
                <span :class="{ 'wh-marked': wh.marked }">{{ shortWarehouseName(wh.name) }}</span>
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
            <td v-if="!hideSizeColumn" class="cell-size font-medium">{{ sizeLabel(row) }}</td>
            <td class="cell-total font-semibold tabular-nums">
              {{ row.total ? formatNumber(row.total) : '' }}
            </td>
            <td
              v-for="(wh, whIndex) in warehouses"
              :key="wh.name"
              class="tabular-nums"
              :class="{ 'wh-divide': isGroupBoundary(whIndex) }"
            >
              <!-- Zeros read as blanks — only real remainders carry a number. -->
              <span v-if="row.quantities[wh.name]">{{
                formatNumber(row.quantities[wh.name])
              }}</span>
            </td>
          </tr>
        </tbody>

        <tfoot>
          <tr>
            <td v-if="!hideSizeColumn" class="cell-size font-medium">Всего</td>
            <td class="cell-total font-bold tabular-nums">
              {{ grandTotal ? formatNumber(grandTotal) : '' }}
            </td>
            <td
              v-for="(wh, whIndex) in warehouses"
              :key="wh.name"
              class="font-semibold tabular-nums"
              :class="{ 'wh-divide': isGroupBoundary(whIndex) }"
            >
              {{ wh.total ? formatNumber(wh.total) : '' }}
            </td>
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

    <!-- The ⋮ mark menu: teleported so the scroll container can't clip it. -->
    <Teleport to="body">
      <div
        v-if="menu"
        class="wh-menu fixed z-50 rounded-card border border-border-subtle bg-surface p-sm shadow-card"
        :style="{ left: `${menu.x}px`, top: `${menu.y}px` }"
      >
        <label class="flex cursor-pointer select-none items-center gap-sm text-base text-primary">
          <input type="checkbox" class="wh-menu-checkbox" :checked="false" @change="toggleMark" />
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
/* While a vertical trackpad gesture is in flight (see v-drag-scroll): the page
   scrolls, the ribbon holds still instead of twitching sideways on the swipe's
   stray deltaX. */
.stock-scroll.wheel-axis-locked {
  overflow-x: hidden;
}
/* While LMB-dragging the ribbon: pan cursor, and no accidental text selection. */
.stock-scroll.drag-scrolling {
  cursor: grabbing;
  user-select: none;
}

/* Compact grid: WB warehouse lists run to dozens of columns — smaller type
   and tighter cells than the generic skin. Heights are EXPLICIT so the
   side-by-side day tables and the shared sizes panel stay row-aligned
   (StockSizesPanel.vue declares the same heights). */
thead th {
  height: 26px;
  padding: 4px 8px;
  font-size: 10px;
}
tbody td {
  height: 24px;
  padding: 3px 8px;
  font-size: 11px;
}
tfoot td {
  height: 26px;
  padding: 3px 8px;
  font-size: 11px;
}

/* Zebra stripes; the frozen pane keeps its own solid backgrounds (declared
   later, so they win over the stripe). */
tbody tr:nth-child(even) td {
  background: #f7f7f7;
}
/* Striped cells would otherwise mask the skin's transparent row hover. */
tbody tr:hover td {
  background: #e8e8e8;
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
td.cell-total,
tbody td:not(.cell-size),
tfoot td:not(.cell-size) {
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
  left: calc(11rem + 12px);
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
td.cell-size {
  width: 6rem;
  min-width: 6rem;
  max-width: 6rem;
}
thead th.col-size,
thead th.col-total {
  left: 0;
  z-index: 30;
  background: #f1f1f1;
}
td.cell-size,
td.cell-total {
  position: sticky;
  left: 0;
  z-index: 20;
  background: #f1f1f1;
}
thead th.col-total,
td.cell-total {
  left: 6rem;
  border-right: 3px solid #e0e0e0;
}
/* No-sizes variant (the two-day comparison: ONE shared sizes panel lives
   OUTSIDE the tables): «Всего» becomes the frozen first column at a fixed
   width so the group labels know their offset. */
.stock-table--no-sizes thead th.col-total,
.stock-table--no-sizes td.cell-total {
  left: 0;
  width: 4.5rem;
  min-width: 4.5rem;
  max-width: 4.5rem;
}
.stock-table--no-sizes thead th.wh-group .wh-group-label {
  left: calc(4.5rem + 12px);
}
/* The skin's row-hover tint sits on the transparent `<tr>`; the solid frozen
   cells would ignore it, so tint them explicitly (matching the skin's
   bg-canvas row hover). */
tbody tr:hover td.cell-size,
tbody tr:hover td.cell-total {
  background: #e8e8e8;
}

/* Totals row: pinned to the bottom edge, separated like the header. */
tfoot td {
  position: sticky;
  bottom: 0;
  border-top: 2px solid #e0e0e0;
  background: #f1f1f1;
  white-space: nowrap;
}
</style>
