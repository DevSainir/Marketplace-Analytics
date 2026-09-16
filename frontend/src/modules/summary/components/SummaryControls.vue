<script setup>
/**
 * The page's one row of controls: the period, its presets, and the price base.
 *
 * Only the period reaches the server. The base is a field the payload already
 * carries for every figure, so switching it is a re-render rather than a
 * re-aggregation of the settlement window.
 *
 * Presets end on the newest SETTLED day, never on today: «30 дней» measured to
 * today would include days no WB report covers yet and read as a collapse in
 * sales.
 */
import PeriodSelector from '@/core/components/PeriodSelector.vue'
import { PRESETS } from '@/core/utils/calendarModel'
import { BASES } from '@/modules/summary/categories'

const props = defineProps({
  dateFrom: { type: String, required: true },
  dateTo: { type: String, required: true },
  /** `{date_from, date_to}` of the settled span, or `null` before it loads. */
  span: { type: Object, default: null },
  revenueBase: { type: String, required: true },
  isAllHistory: { type: Boolean, default: false },
})
const emit = defineEmits(['period', 'preset-days', 'preset-all', 'base'])

/** Whether a preset's window is the one currently loaded. */
function isPreset(days) {
  const end = props.span?.date_to
  if (!end || props.dateTo !== end) return false
  const last = new Date(`${end}T00:00:00`)
  const from = new Date(last.getTime() - (days - 1) * 86400000)
  return props.dateFrom === from.toISOString().slice(0, 10)
}

const chip = (active) =>
  active ? 'bg-action text-white' : 'text-muted hover:bg-hover hover:text-primary'
</script>

<template>
  <div class="mb-lg flex flex-wrap items-center gap-md">
    <PeriodSelector
      :from="dateFrom"
      :to="dateTo"
      :preset-end="span?.date_to ?? ''"
      @update:from="emit('period', $event, dateTo)"
      @update:to="emit('period', dateFrom, $event)"
    />

    <div class="flex items-center gap-xs rounded-btn border border-border-subtle bg-surface p-xs">
      <button
        v-for="preset in PRESETS"
        :key="preset.days"
        type="button"
        class="rounded-btn px-md py-xs text-base font-medium transition"
        :class="chip(isPreset(preset.days))"
        @click="emit('preset-days', preset.days)"
      >
        {{ preset.label }}
      </button>
      <button
        type="button"
        class="rounded-btn px-md py-xs text-base font-medium transition"
        :class="chip(isAllHistory)"
        @click="emit('preset-all')"
      >
        Вся история
      </button>
    </div>

    <div class="flex items-center gap-xs">
      <button
        v-for="base in BASES"
        :key="base.key"
        type="button"
        class="ui-chip"
        :class="{ 'is-on': revenueBase === base.key }"
        @click="emit('base', base.key)"
      >
        {{ base.label }}
      </button>
    </div>
  </div>
</template>
