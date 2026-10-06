<script setup>
/**
 * The metrics table's `<colgroup>`: one column for the frozen labels, then one
 * per leaf of every day, classed by the leaf's `width` in TRAFFIC_COLUMNS.
 *
 * The table is laid out fixed, so these columns — not the cells — decide how
 * a day's width is shared out; the sums live in `styles/MatrixColgroup.css`.
 *
 * Dumb: props in, nothing out.
 */
import { TRAFFIC_COLUMNS } from '@/modules/monitoring/metricsMatrix'

defineProps({
  /** `{iso}` per day section, in display order. */
  days: { type: Array, required: true },
})
</script>

<template>
  <colgroup>
    <col class="matrix-col-label" />
    <template v-for="day in days" :key="day.iso">
      <col
        v-for="column in TRAFFIC_COLUMNS"
        :key="column.key"
        :class="`matrix-col matrix-col--${column.width}`"
      />
    </template>
  </colgroup>
</template>

<style scoped src="./styles/MatrixColgroup.css"></style>
