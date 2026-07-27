<script setup>
/**
 * The identity line above a SKU's metrics: what you are looking at, and the
 * one action that belongs to the SKU itself rather than to its numbers.
 *
 * The vendor code is the heading because that is what the team says out loud;
 * the nm ID follows in the action accent because it is what they paste into
 * WB; the card title is grey because it is the least useful of the three.
 *
 * Dumb by contract: it renders what it is given and emits `toggle-pin`.
 */
defineProps({
  /** @type {{nm_id: number, vendor_code: string|null, title: string|null}} */
  product: { type: Object, required: true },
  /** Fallback label when the card carries no vendor code (the searched term). */
  skuLabel: { type: String, default: '' },
  /** Whether this SKU is in the global pinned row. */
  isPinned: { type: Boolean, default: false },
})

defineEmits(['toggle-pin'])
</script>

<template>
  <div class="mt-lg flex flex-wrap items-baseline gap-x-sm gap-y-xs">
    <!-- Vendor code is the big black heading; the nm ID follows in the
       action accent; title small grey; the pin toggle at the right. -->
    <h2 class="text-h2 font-bold text-primary">{{ product.vendor_code ?? skuLabel }}</h2>
    <span class="text-tiny font-semibold text-action">SKU {{ product.nm_id }}</span>
    <span v-if="product.title" class="text-tiny text-muted">{{ product.title }}</span>
    <button
      type="button"
      class="ml-auto inline-flex items-center gap-xs self-center rounded-btn px-sm py-xs text-tiny font-semibold shadow-soft transition"
      :class="
        isPinned
          ? 'bg-action/10 text-action hover:bg-action/20'
          : 'bg-surface text-primary hover:bg-surface-hover'
      "
      @click="$emit('toggle-pin')"
    >
      <svg
        class="h-3.5 w-3.5 flex-none"
        viewBox="0 0 24 24"
        :fill="isPinned ? 'currentColor' : 'none'"
        stroke="currentColor"
        stroke-width="1.8"
        stroke-linecap="round"
      >
        <path
          d="M16 3a1 1 0 0 1 .95 1.32L15.6 8.4l3.3 3.3a1 1 0 0 1-.4 1.66l-4.75 1.58-1.04 5.2a1 1 0 0 1-1.69.51L7.3 16.93l-3.6 3.6a.75.75 0 0 1-1.06-1.06l3.6-3.6-3.72-3.72a1 1 0 0 1 .51-1.69l5.2-1.04L9.8 4.67A1 1 0 0 1 11.46 4.27l3.3 3.3 4.08-1.36A1 1 0 0 1 16 3Z"
        />
      </svg>
      {{ isPinned ? 'Закреплено' : 'Закрепить' }}
    </button>
  </div>
</template>
