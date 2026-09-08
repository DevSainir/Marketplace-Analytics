<script setup>
/**
 * The ⓘ next to a metric label, and the explanation it opens.
 *
 * Two things had to go wrong before this was a component rather than a `title`
 * attribute and four lines of CSS, and both are worth writing down.
 *
 * **`title` does not work here.** The native tooltip waits about a second,
 * renders in the OS font wherever the cursor happens to be, cannot be styled,
 * and does not exist at all on touch. The reported symptom was «навожу, ничего
 * нет», which is exactly what a one-second delay feels like.
 *
 * **A CSS bubble does not work here either.** The metric labels live inside the
 * result grid's horizontal scroller, and `overflow-x: auto` clips its children
 * on BOTH axes — a bubble positioned above the ⓘ is cut off by a container
 * whose whole job is to clip. So the bubble is teleported to `<body>` and
 * positioned in fixed coordinates, which is the same lesson the design system
 * already records about z-index and cards: an element that must escape a card
 * has to leave the card, not out-rank it.
 *
 * A `<button>` rather than a `<span>` so it is focusable, and the bubble opens
 * on `:focus` as well as hover — on a phone a tap is the only gesture there is.
 */
import { computed, onUnmounted, ref } from 'vue'

defineProps({
  /** The explanation, in the seller's language. */
  text: { type: String, required: true },
})

const anchor = ref(null)
const open = ref(false)
const position = ref({ top: 0, left: 0 })

/** Where the bubble goes, in viewport coordinates. */
const style = computed(() => ({
  top: `${position.value.top}px`,
  left: `${position.value.left}px`,
}))

/**
 * Measure the ⓘ and place the bubble above it, nudged to stay on screen.
 *
 * Measured at open time rather than kept in sync: the page can scroll under an
 * open bubble, and a tooltip that follows its anchor for the two seconds anyone
 * looks at it is not worth a scroll listener.
 */
function show() {
  const rect = anchor.value?.getBoundingClientRect()
  if (!rect) return
  const width = Math.min(320, window.innerWidth * 0.78)
  const margin = 8
  position.value = {
    // Above the icon; the bubble's own transform lifts it clear of its height.
    top: rect.top - margin,
    left: Math.min(
      Math.max(margin, rect.left - 8),
      Math.max(margin, window.innerWidth - width - margin),
    ),
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
    class="ab-tip"
    :aria-label="text"
    data-testid="hint"
    @mouseenter="show"
    @mouseleave="hide"
    @focus="show"
    @blur="hide"
    @click.prevent="open ? hide() : show()"
  >
    ⓘ
  </button>

  <Teleport to="body">
    <span v-if="open" class="ab-tip__bubble" role="tooltip" :style="style">{{ text }}</span>
  </Teleport>
</template>
