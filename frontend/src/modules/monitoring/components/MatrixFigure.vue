<script setup>
/**
 * A matrix cell's printed value: the figure, then its currency sign («45 679с»).
 *
 * A leaf column is ~50px on a 1280px laptop, and «145 679с» wants ~49px of it.
 * A parent can lend the sign its cell's right padding by setting
 * `--matrix-figure-hang` on this element (the metric rows do, see
 * `MatrixMetricsRows.css`): the SIGN alone hangs into it, so a figure whose
 * sign gave way still ends at the content edge and keeps its gap to the
 * neighbouring cell.
 *
 * Where the sign still does not fit, it goes WHOLE: the figure is a one-line
 * wrapping flex box, and a sign that cannot sit beside the digits wraps onto a
 * second line that is clipped away. It used to shrink instead, which printed
 * a sliver of «с» — a mark that reads as a stray bracket, not a currency. The
 * digits never give way: a right-aligned overflow clips the LEADING glyph,
 * which prints a different number («145 679с» as «45 679с»).
 *
 * Dumb: props in, nothing out.
 */
defineProps({
  /** A matrix cell — `figure` and `unit` from `metricsMatrix.js`. */
  cell: { type: Object, required: true },
})
</script>

<template>
  <span class="matrix-figure" :class="cell.unit && 'matrix-figure--signed'"
    ><span class="matrix-figure__num">{{ cell.figure ?? cell.display }}</span
    ><span v-if="cell.unit" class="matrix-figure__unit">{{ cell.unit }}</span></span
  >
</template>

<style scoped>
.matrix-figure {
  display: inline-flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  max-width: 100%;
  /* One line tall; a sign that wrapped is on the second, clipped one. `clip`
     rather than `hidden` so the x-axis stays visible — for the hanging sign,
     and so a figure wider than its cell is never cut at its leading digit. */
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
.matrix-figure__unit {
  margin-right: calc(-1 * var(--matrix-figure-hang, 0px));
}
</style>
