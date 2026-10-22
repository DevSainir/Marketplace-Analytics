<script setup>
/**
 * A matrix cell's printed value: the currency sign, then the figure
 * ("KGS 45,679", "₽4,120").
 *
 * A leaf column is ~50px on a 1280px laptop, and a six-digit sum with its sign
 * does not always fit. Where it does not, the sign goes WHOLE: the figure is a
 * one-line wrapping flex box laid out right to left, so the sign — the last
 * item in source order — is the first to wrap, onto a second line that is
 * clipped away. A sign that shrank instead would print a sliver of a letter, a
 * mark that reads as a stray bracket rather than a currency. The digits never
 * give way: a right-aligned overflow clips the LEADING glyph, which prints a
 * different number ("145,679" as "45,679").
 *
 * Dumb: props in, nothing out.
 */
defineProps({
  /** A matrix cell — `figure` and `unit` from `metricsMatrix.js`. */
  cell: { type: Object, required: true },
})

/** A code ("KGS") is set off from the digits by a space; a symbol ("₽") is not. */
const isCode = (unit) => /[A-Z]$/.test(unit)
</script>

<template>
  <span class="matrix-figure"
    ><span class="matrix-figure__num">{{ cell.figure ?? cell.display }}</span
    ><span
      v-if="cell.unit"
      class="matrix-figure__unit"
      :class="isCode(cell.unit) && 'matrix-figure__unit--code'"
      >{{ cell.unit }}</span
    ></span
  >
</template>

<style scoped>
.matrix-figure {
  display: inline-flex;
  flex-direction: row-reverse;
  flex-wrap: wrap;
  justify-content: flex-start;
  max-width: 100%;
  /* One line tall; a sign that wrapped is on the second, clipped one. `clip`
     rather than `hidden` so the x-axis stays visible, and a figure wider than
     its cell is never cut at its leading digit. */
  height: 1lh;
  overflow-x: visible;
  overflow-y: clip;
  vertical-align: bottom;
}
.matrix-figure__num,
.matrix-figure__unit {
  flex: none;
  white-space: nowrap;
}
.matrix-figure__unit--code {
  margin-right: 0.25em;
}
</style>
