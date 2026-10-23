<script setup>
/**
 * The page's one row of controls: the period and the price base.
 *
 * Only the period reaches the server. The base is a field the payload already
 * carries for every figure, so switching it is a re-render rather than a
 * re-aggregation of the settlement window.
 *
 * The calendar is bounded by the settled span: presets end on its newest day,
 * never on today — "30 days" measured to today would include days no WB report
 * covers yet and read as a collapse in sales — "All time" starts on its
 * oldest, and no day outside it can be picked.
 */
import PeriodSelector from '@/core/components/PeriodSelector.vue'
import { BASES } from '@/modules/summary/categories'
import { MAX_PERIOD_DAYS } from '@/modules/summary/store'

defineProps({
  dateFrom: { type: String, required: true },
  dateTo: { type: String, required: true },
  /** `{date_from, date_to}` of the settled span, or `null` before it loads. */
  span: { type: Object, default: null },
  revenueBase: { type: String, required: true },
})
const emit = defineEmits(['period', 'base'])
</script>

<template>
  <div class="mb-lg flex flex-wrap items-center gap-md">
    <PeriodSelector
      :from="dateFrom"
      :to="dateTo"
      :preset-end="span?.date_to ?? ''"
      :history-from="span?.date_from ?? ''"
      :max="span?.date_to ?? ''"
      :max-days="MAX_PERIOD_DAYS"
      @range="emit('period', $event.from, $event.to)"
    />

    <div class="flex items-center gap-xs phone:w-full">
      <button
        v-for="base in BASES"
        :key="base.key"
        type="button"
        class="ui-chip phone:min-h-11 phone:flex-1"
        :class="{ 'is-on': revenueBase === base.key }"
        @click="emit('base', base.key)"
      >
        {{ base.label }}
      </button>
    </div>
  </div>
</template>
