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
import { ref } from 'vue'

import { formatSku } from '@/core/utils/format'
import { PIN_COLORS } from '@/modules/monitoring/pinColors'
import { useHorizontalPaging } from '@/modules/monitoring/useHorizontalPaging'
import { useDragReorder } from '@/modules/monitoring/useDragReorder'
import { usePinPalette } from '@/modules/monitoring/usePinPalette'

const props = defineProps({
  items: { type: Array, required: true },
  selectedId: { type: Number, default: null },
})

const emit = defineEmits(['select', 'reorder', 'recolor'])

const root = ref(null)

// Sideways paging and the paint mode are each a self-contained interaction with
// its own listeners and lifecycle; they live beside this component so the chip
// row itself stays legible.
const { scroller, overflowing, canScrollLeft, canScrollRight, page, syncArrows } =
  useHorizontalPaging({
    contentSource: () => props.items,
  })

const {
  paletteOpen,
  targetId,
  targetItem,
  targetColor,
  paletteLeft,
  togglePalette,
  claimChipClick,
  applyColor,
} = usePinPalette({
  root,
  items: () => props.items,
  onRecolor: (nmId, color) => emit('recolor', nmId, color),
})

const { dragIndex, dropIndex, handleDragStart, handleDragOver, handleDrop, resetDrag } =
  useDragReorder({
    items: () => props.items,
    onReorder: (order) => emit('reorder', order),
  })

/** A chip click: in paint mode it picks the target, otherwise it analyzes. */
function handleChipClick(item, event) {
  if (claimChipClick(item, event)) return
  emit('select', item)
}

function pinLabel(item) {
  return formatSku(item.vendor_code) || `nm ${item.nm_id}`
}
</script>

<template>
  <div ref="root" class="relative mt-sm flex items-center gap-sm">
    <button
      v-if="overflowing"
      type="button"
      :disabled="!canScrollLeft"
      aria-label="Прокрутить закреплённые влево"
      class="inline-flex h-7 w-7 flex-none items-center justify-center rounded-full border border-border-subtle bg-surface text-muted shadow-soft transition hover:border-action hover:text-action disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:border-border-subtle disabled:hover:text-muted"
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
      class="inline-flex h-7 w-7 flex-none items-center justify-center rounded-full border border-border-subtle bg-surface text-muted shadow-soft transition hover:border-action hover:text-action disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:border-border-subtle disabled:hover:text-muted"
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
      <div class="mt-xs grid grid-cols-3 gap-xs">
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

<style scoped src="./styles/PinnedSkuRow.css"></style>
