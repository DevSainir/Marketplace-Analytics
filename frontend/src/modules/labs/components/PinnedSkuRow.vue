<script setup>
/**
 * The global pinned-SKU chip row («Закрепить»).
 *
 * Dumb by contract: it renders the pins it is given and reports intent —
 * the view owns the store calls. Three interactions live here:
 *
 * - click a chip → `select` (analyze that SKU);
 * - drag a chip onto another → `reorder` with the full new nm_id order.
 *
 * SANDBOX EDIT: the real page adds a third interaction — a pencil that opens
 * a swatch palette to paint each pin its own tint. It is removed here. A
 * per-SKU tint competes with the action colour for meaning, and this design
 * system spends colour on STATE only, so a chip is neutral until you hover it
 * or it is the one being analysed.
 *
 * When more chips are pinned than fit, arrows appear at both ends to page the
 * row sideways (the scrollbar is hidden, and a chip drag is a reorder here —
 * so neither of the usual ways to scroll a ribbon is available).
 */
import { ref } from 'vue'

import { formatSku } from '@/core/utils/format'
import { useHorizontalPaging } from '@/modules/labs/useHorizontalPaging'
import { useDragReorder } from '@/modules/labs/useDragReorder'

const props = defineProps({
  items: { type: Array, required: true },
  selectedId: { type: Number, default: null },
})

const emit = defineEmits(['select', 'reorder'])

const root = ref(null)

// Sideways paging and the paint mode are each a self-contained interaction with
// its own listeners and lifecycle; they live beside this component so the chip
// row itself stays legible.
const { scroller, overflowing, canScrollLeft, canScrollRight, page, syncArrows } =
  useHorizontalPaging({
    contentSource: () => props.items,
  })

const { dragIndex, dropIndex, handleDragStart, handleDragOver, handleDrop, resetDrag } =
  useDragReorder({
    items: () => props.items,
    onReorder: (order) => emit('reorder', order),
  })

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
         hidden); the arrows are siblings, so they stay put. -->
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
        ]"
        @click="emit('select', item)"
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
  </div>
</template>

<style scoped src="./styles/PinnedSkuRow.css"></style>
