<script setup>
/**
 * The global pinned-SKU chip row («Закрепить»).
 *
 * Dumb by contract: it renders the pins it is given and reports intent —
 * the view owns the store calls. Three interactions live here:
 *
 * - click a chip → `select` (analyze that SKU);
 * - drag a chip onto another → `reorder` with the full new nm_id order;
 * - open the pencil → paint mode, whose popover just explains itself until a
 *   chip is clicked. That click picks the pin to paint (rather than selecting
 *   it) and reveals the swatch palette; a swatch click then `recolor`s that
 *   pin. The picked chip shows its live tint over the selection highlight so
 *   the colour is visible as you try it. The mode lasts until the popover
 *   closes, so several chips can be painted in a row.
 *
 * When more chips are pinned than fit, arrows appear at both ends to page the
 * row sideways (the scrollbar is hidden, and a chip drag is a reorder here —
 * so neither of the usual ways to scroll a ribbon is available).
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { PIN_COLORS } from '@/modules/monitoring/pinColors'

const props = defineProps({
  items: { type: Array, required: true },
  selectedId: { type: Number, default: null },
})

const emit = defineEmits(['select', 'reorder', 'recolor'])

const root = ref(null)

// --- sideways paging ------------------------------------------------------
// The arrows only exist while the row actually overflows, and each end's arrow
// disables once that end is reached.
const scroller = ref(null)
const overflowing = ref(false)
const canScrollLeft = ref(false)
const canScrollRight = ref(false)

// Sub-pixel scroll positions never land exactly on 0 / max at fractional zoom
// levels, so treat anything within a pixel of an end as that end.
const EDGE_EPSILON_PX = 1

function syncArrows() {
  const el = scroller.value
  if (!el) return
  const max = el.scrollWidth - el.clientWidth
  overflowing.value = max > EDGE_EPSILON_PX
  canScrollLeft.value = el.scrollLeft > EDGE_EPSILON_PX
  canScrollRight.value = el.scrollLeft < max - EDGE_EPSILON_PX
}

/** Page the row by most of a screenful, keeping a little context in view. */
function page(direction) {
  const el = scroller.value
  if (!el) return
  el.scrollBy({ left: direction * el.clientWidth * 0.8, behavior: 'smooth' })
}

let observer = null

onMounted(() => {
  syncArrows()
  // The row's overflow changes with the viewport, not just with the pin list.
  observer = new ResizeObserver(syncArrows)
  if (scroller.value) observer.observe(scroller.value)
})

onBeforeUnmount(() => observer?.disconnect())

// A pin added, removed, or reordered changes the row's width.
watch(
  () => props.items,
  () => nextTick(syncArrows),
  { deep: true },
)

// --- paint mode -----------------------------------------------------------
// The palette being open IS the mode. Painting is two steps in this order:
// first click a chip to pick WHICH pin to paint, then click a swatch to colour
// it. The target stays selected after a swatch click, so its colour can be
// tweaked, and any other chip can be picked next without leaving the mode.
const paletteOpen = ref(false)
const targetId = ref(null)

// The swatch palette opens anchored under the picked chip; this is its left
// offset within `root` (px), clamped so it never spills past the row's edges.
const paletteLeft = ref(0)
const PALETTE_WIDTH_PX = 256 // w-64

const targetItem = computed(() =>
  targetId.value === null ? null : (props.items.find((it) => it.nm_id === targetId.value) ?? null),
)
const targetColor = computed(() => targetItem.value?.color ?? null)

function togglePalette() {
  paletteOpen.value = !paletteOpen.value
}

/** A chip click: in edit mode pick it as the paint target, else analyze it. */
function handleChipClick(item, event) {
  if (paletteOpen.value) {
    targetId.value = item.nm_id
    anchorPaletteToChip(event.currentTarget)
    return
  }
  emit('select', item)
}

/** Line the palette up under the chip, then pull it back inside the row. */
function anchorPaletteToChip(chipEl) {
  if (!root.value || !chipEl) return
  const rootRect = root.value.getBoundingClientRect()
  const chipRect = chipEl.getBoundingClientRect()
  const maxLeft = Math.max(0, root.value.clientWidth - PALETTE_WIDTH_PX)
  paletteLeft.value = Math.min(Math.max(0, chipRect.left - rootRect.left), maxLeft)
}

/** Colour the chip picked for painting (color = null clears its tint). */
function applyColor(color) {
  if (targetId.value === null) return
  emit('recolor', targetId.value, color)
}

// Close on a click anywhere outside the row — but NOT on a chip click, which
// is the whole point of the mode, and which lands inside this root.
function handleOutsidePointer(event) {
  if (!root.value?.contains(event.target)) paletteOpen.value = false
}

function handleEscape(event) {
  if (event.key === 'Escape') paletteOpen.value = false
}

watch(paletteOpen, (open) => {
  // Leaving the mode forgets which chip was being painted.
  if (!open) targetId.value = null
  const method = open ? 'addEventListener' : 'removeEventListener'
  document[method]('pointerdown', handleOutsidePointer)
  document[method]('keydown', handleEscape)
})

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', handleOutsidePointer)
  document.removeEventListener('keydown', handleEscape)
})

// --- drag to reorder ------------------------------------------------------
// Native HTML5 drag-and-drop: no dependency, and the browser suppresses the
// click that ends a drag, so a reorder can't fall through to `select`.
const dragIndex = ref(null)
const dropIndex = ref(null)

function handleDragStart(index, event) {
  dragIndex.value = index
  event.dataTransfer.effectAllowed = 'move'
  // Firefox refuses to start a drag unless the payload is set.
  event.dataTransfer.setData('text/plain', String(props.items[index].nm_id))
}

function handleDragOver(index, event) {
  if (dragIndex.value === null) return
  // preventDefault is what marks this chip as a valid drop target.
  event.preventDefault()
  event.dataTransfer.dropEffect = 'move'
  dropIndex.value = index
}

function handleDrop(index) {
  const from = dragIndex.value
  resetDrag()
  if (from === null || from === index) return
  const order = props.items.map((item) => item.nm_id)
  const [moved] = order.splice(from, 1)
  order.splice(index, 0, moved)
  emit('reorder', order)
}

function resetDrag() {
  dragIndex.value = null
  dropIndex.value = null
}

/** A pin chip shows the vendor code when the catalogue is synced, nm ID otherwise. */
function pinLabel(item) {
  return item.vendor_code || `nm ${item.nm_id}`
}
</script>

<template>
  <div ref="root" class="relative mt-sm flex items-center gap-sm">
    <button
      v-if="overflowing"
      type="button"
      :disabled="!canScrollLeft"
      aria-label="Прокрутить закреплённые влево"
      class="inline-flex h-7 w-7 flex-none items-center justify-center rounded-full border border-border-subtle bg-surface text-muted shadow-soft transition hover:border-action hover:text-action disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:border-border-subtle disabled:hover:text-muted"
      @click="page(-1)"
    >
      <svg
        class="h-4 w-4"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
      >
        <path d="m15 18-6-6 6-6" />
      </svg>
    </button>

    <!-- The chips scroll horizontally when wider than the canvas (scrollbar
         hidden); the arrows and palette are siblings, so they stay put. -->
    <div
      ref="scroller"
      class="pins-row flex min-w-0 flex-1 items-center gap-sm overflow-x-auto whitespace-nowrap"
      @scroll="syncArrows"
    >
      <button
        v-for="(item, index) in items"
        :key="item.nm_id"
        type="button"
        draggable="true"
        :title="item.title ?? ''"
        class="pin-chip inline-flex flex-none cursor-grab items-center gap-xs rounded-full border border-border-subtle px-sm py-xs text-tiny font-medium text-primary shadow-soft transition active:cursor-grabbing"
        :class="[
          item.nm_id === selectedId ? 'pin-chip--active' : '',
          dragIndex === index ? 'opacity-50' : '',
          dropIndex === index && dragIndex !== index ? 'ring-2 ring-action' : '',
          paletteOpen ? 'cursor-pointer active:cursor-pointer' : '',
          paletteOpen && item.nm_id === targetId ? 'pin-chip--target' : '',
        ]"
        :style="item.color ? { '--pin-tint': item.color } : null"
        @click="handleChipClick(item, $event)"
        @dragstart="handleDragStart(index, $event)"
        @dragover="handleDragOver(index, $event)"
        @drop.prevent="handleDrop(index)"
        @dragend="resetDrag"
      >
        <svg class="h-3 w-3 flex-none text-action" viewBox="0 0 24 24" fill="currentColor">
          <path
            d="M16 3a1 1 0 0 1 .95 1.32L15.6 8.4l3.3 3.3a1 1 0 0 1-.4 1.66l-4.75 1.58-1.04 5.2a1 1 0 0 1-1.69.51L7.3 16.93l-3.6 3.6a.75.75 0 0 1-1.06-1.06l3.6-3.6-3.72-3.72a1 1 0 0 1 .51-1.69l5.2-1.04L9.8 4.67A1 1 0 0 1 11.46 4.27l3.3 3.3 4.08-1.36A1 1 0 0 1 16 3Z"
          />
        </svg>
        {{ pinLabel(item) }}
      </button>
    </div>

    <button
      v-if="overflowing"
      type="button"
      :disabled="!canScrollRight"
      aria-label="Прокрутить закреплённые вправо"
      class="inline-flex h-7 w-7 flex-none items-center justify-center rounded-full border border-border-subtle bg-surface text-muted shadow-soft transition hover:border-action hover:text-action disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:border-border-subtle disabled:hover:text-muted"
      @click="page(1)"
    >
      <svg
        class="h-4 w-4"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
      >
        <path d="m9 18 6-6-6-6" />
      </svg>
    </button>

    <!-- Paint tool, anchored at the row's right edge. -->
    <button
      type="button"
      :aria-pressed="paletteOpen"
      aria-label="Редактировать цвета закреплённых SKU"
      title="Редактировать цвета закреплённых SKU"
      class="inline-flex h-7 w-7 flex-none items-center justify-center rounded-full border border-border-subtle bg-surface text-muted shadow-soft transition hover:border-action hover:text-action"
      :class="paletteOpen ? 'border-action text-action' : ''"
      @click="togglePalette"
    >
      <svg
        class="h-4 w-4"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="1.8"
        stroke-linecap="round"
        stroke-linejoin="round"
      >
        <path d="M12 20h9" />
        <path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z" />
      </svg>
    </button>

    <!-- Hint bubble (before a chip is picked): a compact note in the corner,
         under the pencil, that just explains what to do. -->
    <div
      v-if="paletteOpen && !targetItem"
      class="absolute right-0 top-full z-20 mt-xs w-52 rounded-card border border-border-subtle bg-surface px-sm py-xs shadow-card"
    >
      <p class="text-micro font-medium text-primary">Режим раскраски</p>
      <p class="mt-0.5 text-micro leading-snug text-muted">
        Кликните по закреплённому&nbsp;SKU, чтобы выбрать для него цвет.
      </p>
    </div>

    <!-- Palette popover (after a chip is picked): a solid elevated surface,
         anchored under the chosen chip rather than pinned to the corner. -->
    <div
      v-if="paletteOpen && targetItem"
      class="absolute top-full z-20 mt-xs w-64 rounded-card border border-border-subtle bg-surface p-sm shadow-card"
      :style="{ left: `${paletteLeft}px` }"
    >
      <p class="text-micro font-semibold uppercase tracking-wide text-muted">
        Цвет для «{{ pinLabel(targetItem) }}»
      </p>
      <div class="mt-xs grid grid-cols-7 gap-xs">
        <button
          v-for="color in PIN_COLORS"
          :key="color.value"
          type="button"
          :title="color.label"
          :aria-label="color.label"
          :aria-pressed="targetColor === color.value"
          class="h-6 w-6 rounded-full border border-border-subtle transition hover:border-action"
          :class="targetColor === color.value ? 'ring-2 ring-action' : ''"
          :style="{ backgroundColor: color.value }"
          @click="applyColor(color.value)"
        ></button>
      </div>
      <button
        type="button"
        :aria-pressed="targetColor === null"
        class="mt-sm w-full rounded-btn border border-border-subtle bg-surface px-sm py-xs text-tiny font-medium text-primary transition hover:border-action"
        :class="targetColor === null ? 'border-action text-action' : ''"
        @click="applyColor(null)"
      >
        Убрать цвет
      </button>
      <p class="mt-xs text-tiny text-muted">Цвет виден всей команде.</p>
    </div>
  </div>
</template>

<style scoped>
/* The paint tint rides a custom property rather than `background-color`
   directly: as an inline `background-color` it outranked every state layer,
   so a painted chip could never show hover or selection. Keeping the slot
   free lets the rules below own the chip's background outright. */
.pin-chip {
  background-color: var(--pin-tint, #f1f1f1); /* bg-surface */
}

/* Hover and selection are the SAME treatment, and both are OPAQUE — a
   translucent layer would read differently over each of the 13 paint tints,
   whereas this masks the tint entirely, so every chip highlights alike. */
.pin-chip:hover,
.pin-chip.pin-chip--active {
  border-color: var(--color-action, #007e76);
  background-color: #e0efee; /* bg-hover: action at ~12% over white */
}

/* The chip being painted wins over any hover/selection mask so its live tint
   stays visible while you try colours — the whole point of edit mode. A ring
   (not a background swap) marks it as the target, keeping the colour readable.
   Two class selectors out-specify the single-class rules above; :hover is
   listed so the mask can't reclaim the background as the cursor sits on it. */
.pin-chip.pin-chip--target,
.pin-chip.pin-chip--target:hover {
  background-color: var(--pin-tint, #f1f1f1);
  border-color: var(--color-action, #007e76);
  box-shadow: 0 0 0 2px var(--color-action, #007e76);
}

/* The pin chip row scrolls horizontally without a visible scrollbar (same
   convention as the matrix/stock scroll containers). */
.pins-row {
  scrollbar-width: none;
}
.pins-row::-webkit-scrollbar {
  display: none;
}
</style>
