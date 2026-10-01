<script setup>
/**
 * The P&L's one row of controls: the period, its presets, and the price base.
 *
 * The period lives in the store (it drives the request); the price base is the
 * page's own (`priceBase.js`), so it comes in as a `v-model` — switching it is
 * a re-render, never a request. Split out of `PnlView` when the base switch
 * joined the row and took the view past the component size limit.
 */
import { computed } from 'vue'

import { PRICE_BASES } from '@/modules/finreports/priceBase'
import { shiftIsoDate } from '@/modules/finreports/savedPeriod'
import { useFinReportsStore } from '@/modules/finreports/store'

import PeriodSelector from '@/core/components/PeriodSelector.vue'

defineProps({
  /** `'seller'` or `'paid'` — see `priceBase.js`. */
  priceBase: { type: String, required: true },
})
const emit = defineEmits(['update:priceBase'])

const store = useFinReportsStore()

const PRESETS = [
  { key: 7, label: '7 дней' },
  { key: 30, label: '30 дней' },
  { key: 90, label: '90 дней' },
  { key: 180, label: '180 дней' },
]

const isAllHistory = computed(
  () =>
    store.fullSpan &&
    store.dateFrom === store.fullSpan.date_from &&
    store.dateTo === store.fullSpan.date_to,
)

function isPresetActive(days) {
  if (!store.fullSpan || isAllHistory.value) return false
  const end = store.fullSpan.date_to
  if (store.dateTo !== end) return false
  // `shiftIsoDate`, the same helper the store's own preset uses. Computing it
  // here went through `toISOString`, which converts to UTC: east of Greenwich
  // the start came out a day early and no preset was ever highlighted.
  return store.dateFrom === shiftIsoDate(end, -(days - 1))
}
</script>

<template>
  <div class="mb-lg flex flex-wrap items-center gap-md">
    <PeriodSelector
      :from="store.dateFrom"
      :to="store.dateTo"
      :preset-end="store.fullSpan?.date_to ?? ''"
      @range="store.setPeriod($event.from, $event.to)"
    />

    <!-- Four abreast at 402pt gives each preset ~88px and «Вся история» wraps
         to two lines; two rows of two give every label its own line. -->
    <div
      class="flex items-center gap-xs rounded-btn border border-border-subtle bg-surface p-xs phone:grid phone:w-full phone:grid-cols-2"
    >
      <button
        v-for="preset in PRESETS"
        :key="preset.key"
        type="button"
        class="rounded-btn px-md py-xs text-base font-medium transition phone:min-h-11 phone:flex-1"
        :class="
          isPresetActive(preset.key)
            ? 'bg-action text-white'
            : 'text-muted hover:bg-hover hover:text-primary'
        "
        @click="store.setPresetDays(preset.key)"
      >
        {{ preset.label }}
      </button>
      <button
        type="button"
        class="rounded-btn px-md py-xs text-base font-medium transition phone:min-h-11 phone:flex-1"
        :class="
          isAllHistory ? 'bg-action text-white' : 'text-muted hover:bg-hover hover:text-primary'
        "
        @click="store.setPresetAll()"
      >
        Вся история
      </button>
    </div>

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
