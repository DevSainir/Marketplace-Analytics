<script setup>
/**
 * An ⓘ that explains a column — visible on hover AND on keyboard focus.
 *
 * Not a native `title`: that waits a second, shows nothing on touch, and reads
 * as «наведение ничего не показывает». The icon is what tells the reader the
 * heading has an explanation at all. A click on it is swallowed, so opening the
 * hint inside a sortable header does not also re-sort the table.
 */
defineProps({
  text: { type: String, required: true },
})
</script>

<template>
  <span
    class="hint relative ml-xs inline-flex cursor-help align-middle normal-case tracking-normal text-muted"
    tabindex="0"
    role="note"
    :aria-label="text"
    @click.stop
  >
    <svg viewBox="0 0 16 16" class="h-3.5 w-3.5" aria-hidden="true">
      <circle cx="8" cy="8" r="7" fill="none" stroke="currentColor" stroke-width="1.4" />
      <circle cx="8" cy="4.6" r="0.95" fill="currentColor" />
      <path d="M8 7.2v5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
    </svg>
    <span
      class="hint__tip ui-glass ui-glass--pop pointer-events-none absolute left-1/2 top-full z-30 mt-xs w-56 -translate-x-1/2 rounded-input px-sm py-xs text-left text-tiny font-body text-primary opacity-0 transition-opacity"
    >
      {{ text }}
    </span>
  </span>
</template>

<style scoped>
.hint:hover .hint__tip,
.hint:focus-visible .hint__tip {
  opacity: 1;
}
</style>
