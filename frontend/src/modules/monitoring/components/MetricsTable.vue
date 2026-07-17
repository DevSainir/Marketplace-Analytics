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
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { formatNumber } from '@/core/utils/format'
import { vDragScroll } from '@/core/utils/dragScroll'
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
  /** «Всего» card row — per-day total stock (остаток + оба «в пути»), read-only. */
  stockTotalRows: { type: Array, default: () => [] },
  /** Persisted day notes, keyed by ISO day (commented days only). */
  comments: { type: Object, default: () => ({}) },
  /** ISO days whose note save is in flight (their input is disabled). */
  commentSavingDays: { type: Set, default: () => new Set() },
  /** Disable editing while a save/refresh is in flight. */
  editingDisabled: { type: Boolean, default: false },
})

const emit = defineEmits(['edit', 'comment'])

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
  'manual_catalog',
  'manual_shelves',
])
const zoneHeaderColumns = computed(() =>
  leafColumns.value.filter((leaf) => zonedGroupKeys.has(leaf.key)),
)

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
  return [row.group && `matrix-group--${row.group}`, row.emphasis && 'matrix-row-emphasis']
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

// --- day comments («Комментарий») ----------------------------------------
// One note per day, in a row of its own under the blocks: collapsed to just its
// label (the chevron in the frozen label cell opens it), so the table opens on
// numbers and the notes are there when wanted. Each input is a draft that
// commits on blur — same as an inline cell edit, no per-day save button.
const commentsExpanded = ref(false)

// Drafts by ISO day. Seeded from the persisted notes and re-seeded whenever they
// change (a SKU switch, a window change, a save) — except for the day being
// typed in, whose draft must survive a save landing on another day.
const commentDrafts = ref({})
const focusedCommentDay = ref(null)

watch(
  [() => props.comments, () => props.days],
  () => {
    const drafts = {}
    for (const day of props.days) {
      drafts[day.iso] =
        day.iso === focusedCommentDay.value
          ? (commentDrafts.value[day.iso] ?? '')
          : (props.comments[day.iso] ?? '')
    }
    commentDrafts.value = drafts
  },
  { immediate: true },
)

/** Commit a note on blur, but only when it actually differs from the stored one. */
function commitComment(iso) {
  if (focusedCommentDay.value === iso) focusedCommentDay.value = null
  const body = (commentDrafts.value[iso] ?? '').trim()
  if (body === (props.comments[iso] ?? '')) return
  emit('comment', { day: iso, body })
}

const scroll = ref(null)

/** Start at the right edge: «сегодня» first, older days appear as you scroll left. */
function scrollToNewestDay() {
  const container = scroll.value
  if (container) container.scrollLeft = container.scrollWidth
}

// --- associative-conversion hint -----------------------------------------
// A carts/orders cell shows the campaign's ALL-VARIANT total. Hovering it
// reports the ASSOCIATED share of that total — what the campaign delivered onto
// other size/colour variants — and names them (an always-visible breakdown
// would clutter thousands of cells). Delegated: ONE mouseover listener on the
// scroll container, cells carry their index key in `data-assoc`.
const ASSOC_METRICS = new Set(['carts', 'orders'])
const assocTip = ref(null) // { x, y, above, associated, exact, skus } | null

// Cell -> hover payload, keyed by the `data-assoc` attribute. Follows the rows,
// so an edit to the SKU's own slice keeps the associated remainder in step.
const assocIndex = computed(() => {
  const index = new Map()
  for (const row of props.rows) {
    if (!ASSOC_METRICS.has(row.key)) continue
    for (const cell of row.cells) {
      if (cell?.assoc) index.set(`${row.key}|${cell.day}|${cell.bucket}`, cell)
    }
  }
  return index
})

/** `data-assoc` key for a cell, or null (attribute omitted → no hover). */
function assocData(row, cell) {
  if (!ASSOC_METRICS.has(row.key) || !cell.assoc) return null
  return `${row.key}|${cell.day}|${cell.bucket}`
}

// Room for the tallest breakdown; nearer the viewport floor the tip flips above.
const ASSOC_TIP_MAX_HEIGHT_PX = 260

function onMatrixOver(event) {
  const el = event.target.closest('[data-assoc]')
  const cell = el ? assocIndex.value.get(el.dataset.assoc) : null
  if (!cell) {
    assocTip.value = null
    return
  }
  const rect = el.getBoundingClientRect()
  const above = rect.bottom + ASSOC_TIP_MAX_HEIGHT_PX > window.innerHeight
  assocTip.value = {
    x: rect.left,
    y: above ? rect.top - 6 : rect.bottom + 6,
    above,
    associated: formatNumber(cell.assoc.associated),
    exact: cell.assoc.exact,
    skus: cell.assoc.skus.map((sku) => ({
      key: sku.nm_id,
      label: sku.vendor_code || `nm ${sku.nm_id}`,
      count: formatNumber(sku.count),
      isViewed: sku.isViewed,
    })),
  }
}

function hideAssocTip() {
  assocTip.value = null
}

onMounted(() => {
  scrollToNewestDay()
  // Any scroll strands the fixed-position tip — close it (capture catches the
  // ribbon's own scroll container too).
  document.addEventListener('scroll', hideAssocTip, true)
})
onBeforeUnmount(() => document.removeEventListener('scroll', hideAssocTip, true))
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

    <div
      v-else
      ref="scroll"
      v-drag-scroll
      class="matrix-scroll"
      @mouseover="onMatrixOver"
      @mouseleave="hideAssocTip"
    >
      <table>
        <thead>
          <!-- Row 1: date, one label spanning each day's 8 columns. -->
          <tr>
            <th>Дата</th>
            <th v-for="day in days" :key="day.iso" :colspan="8">{{ day.label }}</th>
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
          <tr v-for="row in rows" :key="row.key" :class="rowClasses(row)">
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

        <!-- Day-bound «Цены»/«Остатки» blocks: ONE row, each day cell holding
             the two tinted cards side by side, in the SAME table so they
             scroll with their day. -->
        <tbody v-if="priceRows.length || stockRows.length" class="matrix-blocks">
          <tr class="matrix-gap" aria-hidden="true">
            <td :colspan="1 + days.length * 8"></td>
          </tr>
          <tr>
            <td>
              <span class="text-micro font-semibold uppercase tracking-wide">
                <span class="text-action">Цены</span><span class="text-muted">/</span
                ><span class="text-accent-indigo">Остатки</span>
              </span>
            </td>
            <td v-for="(day, dayIndex) in days" :key="day.iso" :colspan="8">
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

                <!-- Compact «Всего» card: total stock (остаток + оба «в пути»)
                     for the day. Same tint as «Остатки» — it belongs to it. -->
                <div
                  v-if="stockTotalRows.length"
                  class="day-block day-block--stock day-block--total"
                >
                  <span class="day-block-name">Всего, шт</span>
                  <span class="day-block-total-value tabular-nums">
                    {{ stockTotalRows[0].cells[dayIndex]?.display ?? '' }}
                  </span>
                </div>
              </div>
            </td>
          </tr>
        </tbody>

        <!-- Day comments: ONE note per day, collapsed to its label until the
             chevron opens it. Same table, same scroll container — each input
             sits in its own day section and scrolls with it. -->
        <tbody class="matrix-comments">
          <tr class="matrix-gap" aria-hidden="true">
            <td :colspan="1 + days.length * 8"></td>
          </tr>
          <tr>
            <td>
              <button
                type="button"
                class="comment-toggle"
                :aria-expanded="commentsExpanded"
                @click="commentsExpanded = !commentsExpanded"
              >
                <svg
                  class="comment-chevron h-3 w-3 flex-none"
                  :class="commentsExpanded && 'comment-chevron--open'"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2.4"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                >
                  <path d="m6 9 6 6 6-6" />
                </svg>
                <span class="text-micro font-semibold uppercase tracking-wide">Комментарии</span>
              </button>
            </td>
            <td v-for="day in days" :key="day.iso" :colspan="8">
              <textarea
                v-if="commentsExpanded"
                v-model="commentDrafts[day.iso]"
                rows="2"
                maxlength="2000"
                class="comment-input"
                :disabled="commentSavingDays.has(day.iso)"
                :placeholder="`Заметка за ${day.label}`"
                :aria-label="`Комментарий за ${day.label}`"
                @focus="focusedCommentDay = day.iso"
                @blur="commitComment(day.iso)"
                @keydown.esc.prevent="$event.target.blur()"
              ></textarea>
              <!-- Collapsed: a dot marks the days that DO carry a note, so the
                   row still says where to look before it is opened. -->
              <span v-else-if="comments[day.iso]" class="comment-dot" :title="comments[day.iso]">
                <span class="comment-dot-mark" aria-hidden="true"></span>
                <span class="comment-dot-text">{{ comments[day.iso] }}</span>
              </span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- The associative-conversion breakdown: teleported with fixed coordinates
         so the scroll container can't clip it. Flips above the cell near the
         viewport floor, where a list would otherwise run off-screen. -->
    <Teleport to="body">
      <div
        v-if="assocTip"
        class="fixed z-50 w-72 rounded-card border border-border-subtle bg-surface px-sm py-xs text-tiny leading-snug text-primary shadow-card"
        :style="{
          left: `${assocTip.x}px`,
          top: `${assocTip.y}px`,
          transform: assocTip.above ? 'translateY(-100%)' : null,
        }"
        role="tooltip"
      >
        <!-- The count never wraps away from its dash onto a line of its own. -->
        <p class="text-muted">
          Общее количество ассоциативных конверсий<span class="whitespace-nowrap">
            — <span class="font-semibold text-primary">{{ assocTip.associated }}</span></span
          >
        </p>

        <!-- Every variant behind the cell. The viewed SKU carries the action
             accent, so its own row reads apart from the associated ones — which
             are the rows that sum to the count above. -->
        <ul v-if="assocTip.skus.length" class="mt-xs space-y-0.5">
          <li
            v-for="sku in assocTip.skus"
            :key="sku.key"
            class="flex items-baseline justify-between gap-sm"
            :class="sku.isViewed ? 'font-semibold text-action' : 'text-primary'"
          >
            <span class="truncate">{{ sku.label }}</span>
            <span class="flex-none tabular-nums">{{ sku.count }}</span>
          </li>
        </ul>

        <!-- A two-zone campaign's associated variants are apportioned between
             the zones — WB attributes them per campaign, never per zone. -->
        <p v-if="assocTip.skus.length && !assocTip.exact" class="mt-xs text-muted">
          Разбивка по артикулам в этой зоне показов — оценочная.
        </p>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
/* The native scroll container (replaces PrimeVue's tablecontainer). The
   scrollbar is hidden entirely — macOS overlay scrollbars otherwise pin a
   white track over the table once hovered; scrolling still works via
   trackpad/wheel. */
.matrix-scroll {
  max-height: none;
  overflow: auto;
  scrollbar-width: none;
}
.matrix-scroll::-webkit-scrollbar {
  display: none;
}
/* While a vertical trackpad gesture is in flight (see v-drag-scroll): the page
   scrolls, the ribbon holds still instead of twitching sideways on the swipe's
   stray deltaX. Programmatic scrollLeft still works, so it never fights the
   auto-scroll to the newest day. */
.matrix-scroll.wheel-axis-locked {
  overflow-x: hidden;
}
/* While LMB-dragging the ribbon: pan cursor, and no accidental text selection. */
.matrix-scroll.drag-scrolling {
  cursor: grabbing;
  user-select: none;
}

/* An editable cell reads as plain text but hints affordance on hover/focus.
   min-height keeps a BLANK editable cell (empty content) a real click target. */
.matrix-cell-btn {
  display: inline-block;
  width: 100%;
  min-height: 1.1em;
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

/* «ДРР от продаж»: the headline efficiency number — a step bigger and bold,
   both the frozen label and every value cell (the cell button/span carry an
   explicit font-weight, so target them directly, not just the td). */
.app-datatable--matrix tbody.matrix-metrics tr.matrix-row-emphasis td {
  font-size: 13px;
}
.app-datatable--matrix tbody.matrix-metrics tr.matrix-row-emphasis td .matrix-cell-btn,
.app-datatable--matrix tbody.matrix-metrics tr.matrix-row-emphasis td span {
  font-size: 13px;
  font-weight: 700;
}
.app-datatable--matrix
  tbody.matrix-metrics
  tr.matrix-row-emphasis
  td:first-child
  .matrix-row-label {
  font-size: 14px;
  font-weight: 700;
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
/* The «Всего» card: shares the «Остатки» tint (it IS stock data), but only
   takes the width its number needs — the two main cards shrink around it. */
.day-block--total {
  flex: 0 1 auto;
  align-items: center;
  justify-content: center;
  gap: 1px;
}
.day-block-total-value {
  color: #101010;
  font-size: 13px;
  font-weight: 600;
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
   take its content so the label keeps the left edge. min-width keeps a BLANK
   cell clickable — content-sized, it would collapse to zero width. */
.day-block-line .matrix-cell-btn {
  width: auto;
  min-width: 2.5rem;
}
.day-block-input {
  width: 6rem;
  text-align: right;
}

/* --- day comments row ------------------------------------------------------
   Same open-card treatment as the blocks above (the heavy prefixes out-rank the
   skin's zebra/hover/day-border rules), so the notes read as a strip of inputs
   rather than another grid of cells. */
.app-datatable--matrix tbody.matrix-comments tr td,
.app-datatable--matrix tbody.matrix-comments tr:hover td {
  background: transparent;
  border-left: none;
  padding: 3px 6px;
  vertical-align: top;
}
/* Frozen label cell: SOLID so the inputs scroll underneath it, not through it. */
.app-datatable--matrix tbody.matrix-comments tr td:first-child,
.app-datatable--matrix tbody.matrix-comments tr:hover td:first-child {
  background: #f1f1f1;
  padding: 9px 8px;
}
.app-datatable--matrix tbody.matrix-comments tr.matrix-gap td,
.app-datatable--matrix tbody.matrix-comments tr.matrix-gap:hover td {
  background: transparent;
  border: none;
  height: 10px;
  padding: 0;
}

/* The disclosure control IS the row label: chevron + name, one click target. */
.comment-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0;
  border: none;
  background: transparent;
  color: #667085;
  cursor: pointer;
}
.comment-toggle:hover,
.comment-toggle:focus-visible {
  color: #101010;
  outline: none;
}
.comment-chevron {
  transition: transform 150ms ease;
}
.comment-chevron--open {
  transform: rotate(180deg);
}

.comment-input {
  width: 100%;
  resize: vertical;
  padding: 5px 8px;
  border: 1px solid var(--color-border-subtle, #e4e4e7);
  border-radius: 8px;
  background: var(--color-canvas, #fafafa);
  color: #101010;
  font: inherit;
  font-size: 12px;
  line-height: 1.35;
}
.comment-input::placeholder {
  color: #98a2b3;
}
.comment-input:focus {
  border-color: var(--color-action, #2f7d68);
  outline: 2px solid color-mix(in srgb, var(--color-action, #2f7d68) 30%, transparent);
  outline-offset: 0;
}
.comment-input:disabled {
  opacity: 0.6;
}

/* Collapsed row: a one-line trace of the days that carry a note. */
.comment-dot {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  color: #667085;
  font-size: 11px;
}
.comment-dot-mark {
  flex: none;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--color-action, #2f7d68);
}
.comment-dot-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
