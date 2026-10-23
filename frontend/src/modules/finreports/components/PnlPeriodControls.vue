<script setup>
/**
 * The P&L's one row of controls: the period and the price base.
 *
 * The period lives in the store (it drives the request); its presets are the
 * calendar's own, bounded by the harvested span — they end on the newest
 * settled day, "All time" starts on the oldest, and the calendar grays out
 * every day outside it. The price base is the page's own (`priceBase.js`), so
 * it comes in as a `v-model` — switching it is a re-render, never a request.
 */
import { PRICE_BASES } from '@/modules/finreports/priceBase'
import { useFinReportsStore } from '@/modules/finreports/store'

import PeriodSelector from '@/core/components/PeriodSelector.vue'

defineProps({
  /** `'seller'` or `'paid'` — see `priceBase.js`. */
  priceBase: { type: String, required: true },
})
const emit = defineEmits(['update:priceBase'])

const store = useFinReportsStore()
</script>

<template>
  <div class="mb-lg flex flex-wrap items-center gap-md">
    <PeriodSelector
      :from="store.dateFrom"
      :to="store.dateTo"
      :preset-end="store.fullSpan?.date_to ?? ''"
      :history-from="store.fullSpan?.date_from ?? ''"
      :max="store.fullSpan?.date_to ?? ''"
      @range="store.setPeriod($event.from, $event.to)"
    />

    <div class="flex items-center gap-xs phone:w-full">
      <button
        v-for="base in PRICE_BASES"
        :key="base.key"
        type="button"
        class="ui-chip phone:min-h-11 phone:flex-1"
        :class="{ 'is-on': priceBase === base.key }"
        @click="emit('update:priceBase', base.key)"
      >
        {{ base.label }}
      </button>
    </div>
  </div>
</template>
