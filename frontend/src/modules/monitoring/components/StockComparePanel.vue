<script setup>
/**
 * The «Остатки по складам» section: the whole period as one grid.
 *
 * A stock number alone says nothing — what the team reads is the MOVEMENT from
 * one day to the next, so the section shows days side by side: one column group
 * per day, two of them on screen, scrolled sideways through the period. That
 * period is the page's own, chosen once at the top — this section has no day
 * pickers of its own, because two controls for one question is how the two
 * disagree.
 *
 * Dumb by contract: it renders the days it is given.
 */
import { computed } from 'vue'

import StockCompareTable from '@/modules/monitoring/components/StockCompareTable.vue'

const props = defineProps({
  /** @type {Array<{stat_date: string, stock: ?object}>} oldest day first. */
  days: { type: Array, default: () => [] },
  /** The union of every day's sizes, so a row lines up across the period. */
  sizeOrder: { type: Array, default: () => [] },
  /** Dim the grid while a reload is in flight. */
  loading: { type: Boolean, default: false },
})

/** "2026-07-11" → "11.07.2026" — the group label over each day's columns. */
function dayLabel(iso) {
  if (!iso) return '—'
  const [y, m, d] = iso.split('-')
  return `${d}.${m}.${y}`
}

const columns = computed(() =>
  props.days.map((day) => ({
    key: day.stat_date,
    label: dayLabel(day.stat_date),
    cells: day.stock?.cells ?? [],
  })),
)
</script>

<template>
  <section class="mt-lg" aria-label="Остатки по складам">
    <h2 class="text-h3 font-semibold text-primary">Остатки по складам</h2>

    <StockCompareTable
      class="mt-sm"
      :class="loading ? 'opacity-60' : ''"
      :days="columns"
      :size-order="sizeOrder"
      empty-message="Нет складских остатков по этому SKU за выбранный период."
    />
  </section>
</template>
