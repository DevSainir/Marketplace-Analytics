<script setup>
/**
 * The ⓘ beside a label, and the explanation it opens — the app's one hint.
 *
 * There were five: the browser's `title`, advertising's ⓘ with a glass bubble,
 * a copy of that inside the summary's cards, the A/B tests' dark bubble, and a
 * «Как использовать» link. This is the A/B mechanics in the advertising look.
 *
 * Why not `title`: it waits about a second, cannot be styled and does not
 * exist on touch — «навожу, ничего нет». Why teleported: the labels it sits on
 * live inside table scrollers, and `overflow: auto` clips a child bubble on
 * both axes, so the bubble leaves the table for `<body>` and is placed in
 * fixed coordinates. A `<button>`, so it is focusable and a tap opens it on a
 * phone, where hover does not exist.
 */
import { computed, onUnmounted, ref } from 'vue'

defineProps({
  /** The explanation, in the seller's language. */
  text: { type: String, required: true },
})

const anchor = ref(null)
const open = ref(false)
const position = ref({ top: 0, left: 0, width: 288 })

const style = computed(() => ({
  top: `${position.value.top}px`,
  left: `${position.value.left}px`,
  width: `${position.value.width}px`,
}))

/** Measure the ⓘ and place the bubble under it, nudged to stay on screen. */
function show() {
  const rect = anchor.value?.getBoundingClientRect()
  if (!rect) return
  const margin = 8
  const width = Math.min(288, window.innerWidth - 2 * margin)
  position.value = {
    top: rect.bottom + 6,
    left: Math.min(Math.max(margin, rect.left - 12), window.innerWidth - width - margin),
    width,
  }
  open.value = true
}

function hide() {
  open.value = false
}

onUnmounted(hide)
</script>

<template>
  <button
    ref="anchor"
    type="button"
    class="ml-xs inline-flex flex-none cursor-help items-center align-middle text-muted transition hover:text-action"
    :aria-label="text"
    data-testid="hint"
    @mouseenter="show"
    @mouseleave="hide"
    @focus="show"
    @blur="hide"
    @click.prevent.stop="open ? hide() : show()"
  >
    <svg viewBox="0 0 16 16" class="h-3.5 w-3.5" aria-hidden="true">
      <circle cx="8" cy="8" r="7" fill="none" stroke="currentColor" stroke-width="1.4" />
      <circle cx="8" cy="4.6" r="0.95" fill="currentColor" />
      <path d="M8 7.2v5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
    </svg>
  </button>

  <Teleport to="body">
    <span
      v-if="open"
      class="ui-glass ui-glass--pop pointer-events-none fixed z-50 whitespace-normal rounded-input px-sm py-xs text-left text-tiny font-normal normal-case tracking-normal text-primary"
      role="tooltip"
      :style="style"
    >
      {{ text }}
    </span>
  </Teleport>
</template>
