<script setup>
/**
 * A matrix cell's printed value: the figure, then its currency sign («45 679с»).
 *
 * The sign sits in its own element that may shrink to nothing, so in a ~52px
 * leaf column a long figure keeps every digit and loses the sign instead. The
 * other way round is not cosmetic: a right-aligned overflow clips the LEADING
 * glyph, which prints a different number («145 679с» as «45 679с»). Where the
 * sign fits, it is there.
 *
 * Dumb: props in, nothing out.
 */
defineProps({
  /** A matrix cell — `figure` and `unit` from `metricsMatrix.js`. */
  cell: { type: Object, required: true },
})
</script>

<template>
  <span class="matrix-figure"
    ><span class="matrix-figure__num">{{ cell.figure ?? cell.display }}</span
    ><span v-if="cell.unit" class="matrix-figure__unit">{{ cell.unit }}</span></span
  >
</template>

<style scoped>
.matrix-figure {
  display: inline-flex;
  max-width: 100%;
  justify-content: flex-end;
  vertical-align: bottom;
}
.matrix-figure__num {
  flex: none;
}
.matrix-figure__unit {
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
}
</style>
