<script setup>
/**
 * A product card's photo, at one of three fixed sizes.
 *
 * Three screens show the seller their own catalogue — the monitoring SKU
 * search, «Сравнение SKU» and the per-SKU P&L — and on all three the picture is
 * what a seller recognises a card by, faster than either article number. The
 * component exists rather than three `<img>` tags because the fallback is the
 * hard part and it has to behave the same everywhere: an empty slot must occupy
 * EXACTLY the space a photo would, or a row's height changes depending on
 * whether WB happened to serve the image, and a table of forty SKUs ripples as
 * it loads.
 *
 * Three things about the `<img>` are load-bearing:
 *
 * * `referrerpolicy="no-referrer"` — the URL is WB's CDN, so the request leaves
 *   our origin. WB may learn that a card was viewed; it does not also get told
 *   which page of ours was looking. This is the only third-party origin the
 *   production CSP names (see `docker/snippets/security-headers.conf`), and the
 *   backend stores only URLs that passed its own WB-host check, so `src` cannot
 *   be pointed anywhere else by a WB response.
 * * `loading="lazy"` + `decoding="async"` — the P&L table renders every SKU of
 *   a window at once. Eager loading turns opening it into a few hundred CDN
 *   requests before the first row paints.
 * * `@error` — a WB URL is a cache of what the CDN served at the last catalogue
 *   sync, and a re-shot card 404s until the next one. A broken-image glyph in a
 *   data table reads as "this row is broken"; the placeholder reads as "no
 *   photo", which is the truth.
 */
import { computed, ref } from 'vue'

const props = defineProps({
  /** WB CDN URL, or null/'' when the catalogue holds no photo for this SKU. */
  src: { type: String, default: null },
  /** What the photo is of — the article, for the alt text. */
  label: { type: String, default: '' },
  /** `sm` for table rows, `md` for dropdown lists, `lg` for the SKU header. */
  size: { type: String, default: 'sm' },
})

/** Fixed boxes, so a row's height never depends on whether the image loaded. */
const BOXES = {
  sm: 'h-8 w-8',
  md: 'h-10 w-10',
  lg: 'h-16 w-16',
}

const failed = ref(false)

const box = computed(() => BOXES[props.size] ?? BOXES.sm)
const showImage = computed(() => !!props.src && !failed.value)
</script>

<template>
  <div
    class="flex-none overflow-hidden rounded-input border border-border-subtle bg-canvas"
    :class="box"
  >
    <img
      v-if="showImage"
      :src="src"
      :alt="label ? `Фото ${label}` : 'Фото товара'"
      class="h-full w-full object-cover"
      loading="lazy"
      decoding="async"
      referrerpolicy="no-referrer"
      @error="failed = true"
    />
    <!-- The placeholder is a glyph, not a spinner: «нет фото» is a settled
         state, and a table full of spinners that never resolve is worse than
         an obviously empty box. -->
    <svg
      v-else
      class="h-full w-full p-1 text-muted opacity-40"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="1.5"
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
    >
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <circle cx="8.5" cy="8.5" r="1.5" />
      <path d="m21 15-5-5L5 21" />
    </svg>
  </div>
</template>
