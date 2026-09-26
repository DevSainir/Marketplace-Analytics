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
 * LAB-ONLY: «Складов» over the grid is a debug knob — N shows exactly N
 * warehouse columns per day, to check the grid's look at any count. It is not
 * a feature and does not go to /monitoring.
 *
 * Dumb by contract: it renders the days it is given.
 */
import { computed, ref } from 'vue'

import StockCompareTable from '@/modules/labs/components/StockCompareTable.vue'

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

/** Empty = every warehouse. */
const warehouseLimit = ref(null)

/** Anything that is not a whole number ≥ 1 means «all» — an empty field, a 0. */
function setLimit(event) {
  const n = Math.floor(Number(event.target.value))
  warehouseLimit.value = event.target.value !== '' && n >= 1 ? n : null
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
    <div class="flex flex-wrap items-center justify-between gap-sm">
      <h2 class="text-h3 font-semibold text-primary">Остатки по складам</h2>
      <label class="inline-flex items-center gap-xs text-tiny font-medium text-muted">
        Складов (отладка)
        <input
          type="number"
          min="1"
          step="1"
          inputmode="numeric"
          placeholder="все"
          class="w-16 rounded-btn border border-border-subtle bg-surface px-sm py-xs text-tiny text-primary tabular-nums"
          :value="warehouseLimit ?? ''"
          @input="setLimit"
        />
      </label>
    </div>

    <StockCompareTable
      class="mt-sm"
      :class="loading ? 'opacity-60' : ''"
      :days="columns"
      :size-order="sizeOrder"
      :warehouse-limit="warehouseLimit"
      empty-message="Нет складских остатков по этому SKU за выбранный период."
    />
  </section>
</template>
