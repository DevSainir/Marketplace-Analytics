<script setup>
/**
 * The sort mark beside a table head, for tables we draw ourselves — drawn the
 * way PrimeVue's tables draw theirs: a faint double arrow while the column is
 * not the sort, one arrow in the action colour once it is.
 *
 * The heatmap printed ↕ ↓ ↑ as text glyphs beside PrimeVue's icons elsewhere.
 */
defineProps({
  /** `none` | `asc` | `desc`. */
  state: { type: String, default: 'none' },
})
</script>

<template>
  <svg
    class="ml-1 inline-block h-3 w-3 align-middle"
    :class="state === 'none' ? 'text-muted' : 'text-action'"
    viewBox="0 0 12 12"
    fill="none"
    stroke="currentColor"
    stroke-width="1.4"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <template v-if="state === 'none'">
      <path d="M4 2v8M2 4l2-2 2 2" />
      <path d="M8 10V2M6 8l2 2 2-2" />
    </template>
    <path v-else-if="state === 'desc'" d="M6 2v8M3 7l3 3 3-3" />
    <path v-else d="M6 10V2M3 5l3-3 3 3" />
  </svg>
</template>
