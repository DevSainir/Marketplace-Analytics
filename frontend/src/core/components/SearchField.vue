<script setup>
/**
 * The app's one search box: a magnifier on the left, a ✕ once there is
 * something to clear, Esc clears too.
 *
 * The P&L folded its search into an icon you had to click open, advertising
 * kept a bare input with no icon, the A/B list a borderless one; each worded
 * its placeholder differently. Always open, because a search you have to find
 * first is one nobody uses.
 */
import { computed, useAttrs } from 'vue'

// The wrapper takes the layout classes (`w-72`); everything else — a
// `data-testid`, an `id` — belongs on the input the caller is talking about.
defineOptions({ inheritAttrs: false })
const attrs = useAttrs()
const inputAttrs = computed(() =>
  Object.fromEntries(Object.entries(attrs).filter(([key]) => key !== 'class' && key !== 'style')),
)

defineProps({
  modelValue: { type: String, default: '' },
  placeholder: { type: String, default: 'Vendor code or WB ID, category, brand' },
  /** `sm` — 36px, beside the calendar or a 36px select. */
  size: { type: String, default: 'md' },
  ariaLabel: { type: String, default: 'Search' },
})
const emit = defineEmits(['update:modelValue'])
</script>

<template>
  <div class="relative" :class="attrs.class" :style="attrs.style">
    <svg
      class="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="2"
      stroke-linecap="round"
      aria-hidden="true"
    >
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.5-3.5" />
    </svg>
    <input
      v-bind="inputAttrs"
      :value="modelValue"
      type="search"
      :placeholder="placeholder"
      :aria-label="ariaLabel"
      class="ui-input w-full pl-9 pr-9"
      :class="{ 'ui-input--sm pl-9 pr-9': size === 'sm' }"
      @input="emit('update:modelValue', $event.target.value)"
      @keydown.esc="emit('update:modelValue', '')"
    />
    <button
      v-if="modelValue"
      type="button"
      aria-label="Clear search"
      class="absolute right-1 top-1/2 flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-full text-muted transition hover:bg-hover hover:text-primary"
      @click="emit('update:modelValue', '')"
    >
      <svg
        class="h-4 w-4"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        aria-hidden="true"
      >
        <path d="M6 6l12 12M18 6L6 18" />
      </svg>
    </button>
  </div>
</template>
