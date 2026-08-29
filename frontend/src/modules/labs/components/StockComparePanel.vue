<script setup>
/**
 * The «Остатки по складам» panel: two snapshot days side by side.
 *
 * Two, not one, because a stock number alone says nothing — what the team reads
 * is the MOVEMENT between yesterday and today (right = today, left = yesterday
 * by default). Each side has its own day picker so any two days can be
 * compared, and both tables render the same size rows (`sizeOrder`) so a row on
 * the left lines up with the same row on the right.
 *
 * Dumb by contract: it renders the sides it is given and reports intent.
 */
import DayPicker from '@/core/components/DayPicker.vue'
import StockBreakdownTable from '@/modules/labs/components/StockBreakdownTable.vue'

defineProps({
  /** @type {{left: {date, loading, stock}, right: {date, loading, stock}}} */
  sides: { type: Object, required: true },
  /** Warehouses currently marked «на отгрузку» for this SKU. */
  markedWarehouses: { type: Array, default: () => [] },
  /** The union of sizes both tables render, so their rows align. */
  sizeOrder: { type: Array, default: () => [] },
  /** Latest selectable day (no snapshot exists past it). */
  maxDate: { type: String, required: true },
})

defineEmits(['change-day', 'toggle-mark'])
</script>

<template>
  <!-- Warehouses × sizes stock: TWO snapshot days side by side for
     visual dynamics (right = today, left = yesterday by default);
     each side has its own day picker and its own size column, and
     both render the same rows (see `sharedStockSizes`). -->
  <section class="mt-lg" aria-label="Остатки по складам">
    <h2 class="text-h3 font-semibold text-primary">Остатки по складам</h2>
    <!-- Side by side is the whole point of the panel, but at 402pt each side
         gets ~190px and neither table is readable — so on a phone the pair
         stacks and the comparison becomes vertical. Each side keeps its own day
         picker, which is what labels it once they are no longer left/right. -->
    <div class="mt-sm flex gap-md phone:flex-col">
      <div v-for="side in ['left', 'right']" :key="side" class="min-w-0 flex-1">
        <DayPicker
          class="mb-xs"
          :model-value="sides[side].date"
          :max="maxDate"
          :aria-label="side === 'left' ? 'День левой таблицы' : 'День правой таблицы'"
          @update:model-value="$emit('change-day', side, $event)"
        />
        <StockBreakdownTable
          :class="sides[side].loading ? 'opacity-60' : ''"
          :cells="sides[side].stock?.cells ?? []"
          :marked-warehouses="markedWarehouses"
          :size-order="sizeOrder"
          empty-message="Нет снимка остатков за выбранный день."
          @toggle-mark="$emit('toggle-mark', $event)"
        />
      </div>
    </div>
  </section>
</template>
