<script setup>
/**
 * The identity line above a SKU's metrics: what you are looking at, and the
 * one action that belongs to the SKU itself rather than to its numbers.
 *
 * The vendor code is the heading because that is what the team says out loud;
 * the nm ID follows in the action accent because it is what they paste into
 * WB; the card title is grey because it is the least useful of the three.
 *
 * Between the vendor code and the nm ID sits the card's buyer rating — the
 * stars WB prints on the storefront. The seller API has it:
 * `sales-funnel/products` → `product.feedbackRating`, which matched the
 * storefront's `reviewRating` on every card checked (2026-09-26). Its sibling
 * `productRating` is WB's 0–10 card-quality score, a different number.
 *
 * Under the line, two ways out: the card as a buyer sees it and the card in
 * the seller's editor (`wbLinks.js`).
 *
 * Dumb by contract: it renders what it is given and emits `toggle-pin`.
 */
import { formatSku } from '@/core/utils/format'
import { sellerCardUrl, storefrontCardUrl } from '@/modules/monitoring/wbLinks'

defineProps({
  /** @type {{nm_id: number, vendor_code: string|null, title: string|null, feedback_rating?: number|null}} */
  product: { type: Object, required: true },
  /** Fallback label when the card carries no vendor code (the searched term). */
  skuLabel: { type: String, default: '' },
  /** Whether this SKU is in the global pinned row. */
  isPinned: { type: Boolean, default: false },
})

defineEmits(['toggle-pin'])

/** 4.7 → «4,7»; WB rounds to one decimal and so do we. */
function formatRating(value) {
  return value.toLocaleString('ru-RU', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
}
</script>

<template>
  <div class="mt-lg flex flex-wrap items-baseline gap-x-sm gap-y-xs">
    <!-- Vendor code is the big black heading; the nm ID follows in the
       action accent; title small grey; the pin toggle at the right. -->
    <h2 class="text-h2 font-bold text-primary">{{ formatSku(product.vendor_code ?? skuLabel) }}</h2>
    <!-- A card with no reviews yet has no rating — nothing, rather than «0». -->
    <span
      v-if="product.feedback_rating"
      class="inline-flex items-center gap-xs text-tiny font-semibold text-primary"
      :aria-label="`Оценка ${formatRating(product.feedback_rating)} из 5`"
    >
      {{ formatRating(product.feedback_rating) }}
      <svg class="h-3.5 w-3.5 flex-none text-status-warning" viewBox="0 0 24 24" aria-hidden="true">
        <path
          fill="currentColor"
          d="M12 2.8l2.8 5.8 6.3.9-4.6 4.4 1.1 6.3L12 17.2l-5.6 3 1.1-6.3L2.9 9.5l6.3-.9L12 2.8z"
        />
      </svg>
    </span>
    <span class="text-tiny font-semibold text-action">SKU {{ product.nm_id }}</span>
    <span v-if="product.title" class="text-tiny text-muted">{{ product.title }}</span>
    <button
      type="button"
      class="ml-auto inline-flex items-center gap-xs self-center rounded-btn px-sm py-xs text-tiny font-semibold shadow-soft transition"
      :class="
        isPinned
          ? 'bg-action/10 text-action hover:bg-action/20'
          : 'bg-surface text-primary hover:bg-hover'
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

  <!-- Named links, not bare icons: an arrow alone is ambiguous, and both go to
       WB, so the words are what tells them apart. A new tab, because the
       reader is coming back to this table. -->
  <div class="mt-xs flex flex-wrap gap-x-md gap-y-xs text-tiny">
    <a
      v-for="link in [
        { href: storefrontCardUrl(product.nm_id), label: 'Карточка на WB' },
        { href: sellerCardUrl(product.nm_id), label: 'В кабинете продавца' },
      ]"
      :key="link.label"
      :href="link.href"
      target="_blank"
      rel="noopener noreferrer"
      class="inline-flex items-center gap-xs font-medium text-muted underline-offset-2 transition hover:text-action hover:underline"
    >
      {{ link.label }}
      <svg
        class="h-3 w-3 flex-none"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        aria-hidden="true"
      >
        <path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" />
      </svg>
      <span class="sr-only">(откроется в новой вкладке)</span>
    </a>
  </div>
</template>
