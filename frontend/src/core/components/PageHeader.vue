<script setup>
/**
 * The top of every page: an optional «← back» link, the title, a one-line
 * subtitle, and the page's own actions on the right.
 *
 * Pages wrote their own, and they drifted: a subtitle at body size on one and
 * tiny on another, a back link at two sizes, actions aligned to the bottom on
 * one and the middle on the next, some pages with no subtitle at all. What a
 * page says is its own; where and at what size it says it is this file's.
 *
 * The default slot is for what does not fit one line under the title — the
 * logistics page's paragraph on method, the A/B list's rules.
 */
import { RouterLink } from 'vue-router'

defineProps({
  title: { type: String, required: true },
  subtitle: { type: String, default: '' },
  /** `{ to, label }` for a page reached from another one; `null` for a top-level page. */
  back: { type: Object, default: null },
})
</script>

<template>
  <header class="mb-lg flex flex-wrap items-end justify-between gap-md">
    <div class="min-w-0">
      <RouterLink
        v-if="back"
        :to="back.to"
        class="text-base font-medium text-action hover:underline"
      >
        ← {{ back.label }}
      </RouterLink>
      <h1 class="text-h2 font-bold text-primary" :class="{ 'mt-sm': back }">{{ title }}</h1>
      <p v-if="subtitle" class="mt-xs max-w-3xl text-base text-muted">{{ subtitle }}</p>
      <slot />
    </div>
    <div v-if="$slots.actions" class="flex flex-wrap items-center gap-sm phone:w-full">
      <slot name="actions" />
    </div>
  </header>
</template>
