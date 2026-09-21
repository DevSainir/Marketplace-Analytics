<script setup>
/**
 * The «Остатки по складам» panel: two snapshot days in ONE grid.
 *
 * Two days, not one, because a stock number alone says nothing — what the team
 * reads is the MOVEMENT between yesterday and today (right = today, left =
 * yesterday by default). They used to be two separate tables; now they are two
 * column GROUPS of a single full-width table, so the size column is printed
 * once, a row reads straight across both days, and the grid scrolls as one (see
 * StockCompareTable.vue). Each side keeps its own day picker, sitting over its
 * own half of the grid.
 *
 * Dumb by contract: it renders the sides it is given and reports intent.
 */
import { computed } from 'vue'

import DayPicker from '@/core/components/DayPicker.vue'
import StockCompareTable from '@/modules/monitoring/components/StockCompareTable.vue'

const props = defineProps({
  /** @type {{left: {date, loading, stock}, right: {date, loading, stock}}} */
  sides: { type: Object, required: true },
  /** The union of both days' sizes, so a row lines up across the pair. */
  sizeOrder: { type: Array, default: () => [] },
  /** Latest selectable day (no snapshot exists past it). */
  maxDate: { type: String, required: true },
})

defineEmits(['change-day'])

/** "2026-07-11" → "11.07.2026" — the group label over each day's columns. */
function dayLabel(iso) {
  if (!iso) return '—'
  const [y, m, d] = iso.split('-')
  return `${d}.${m}.${y}`
}

/** Oldest day first: the table renders the groups left → right in this order. */
const days = computed(() =>
  ['left', 'right'].map((key) => ({
    key,
    label: dayLabel(props.sides[key].date),
    loading: props.sides[key].loading,
    cells: props.sides[key].stock?.cells ?? [],
  })),
)
</script>

<template>
  <section class="mt-lg" aria-label="Остатки по складам">
    <h2 class="text-h3 font-semibold text-primary">Остатки по складам</h2>

    <!-- One picker per day group, each over its own half of the grid (the
         table's day groups split the width left by the frozen size column).
         On a phone they simply wrap. -->
    <div class="mt-sm flex gap-md phone:flex-wrap">
      <DayPicker
        v-for="side in ['left', 'right']"
        :key="side"
        class="min-w-0 flex-1"
        :model-value="sides[side].date"
        :max="maxDate"
        :aria-label="side === 'left' ? 'День левой половины' : 'День правой половины'"
        @update:model-value="$emit('change-day', side, $event)"
      />
    </div>

    <StockCompareTable
      class="mt-xs"
      :days="days"
      :size-order="sizeOrder"
      empty-message="Нет снимка остатков за выбранные дни."
    />
  </section>
</template>
