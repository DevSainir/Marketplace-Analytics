<script setup>
/**
 * The grid's own controls: what is painted, and how.
 *
 * Left: the painted metric, ⇄, and an optional second metric — when one is
 * chosen every cell carries two numbers, the painted one on top. Each select
 * is as wide as its longest option, no wider. Right: where the norm comes
 * from (the median, or a number typed per article), the column width (day /
 * week / month), and whether a row is compared with its own days or with
 * every other row. What a row stands for is `GroupingChips`, above the card
 * like on every other page.
 *
 * Native selects, as everywhere in this app: they are the accessible picker on
 * a phone, and the list of twenty-five metrics is exactly what one is for.
 */
import { METRIC_GROUPS, metricLabel } from '@/modules/heatmap/metrics'

defineProps({
  metric: { type: String, required: true },
  metric2: { type: String, default: null },
  period: { type: String, required: true },
  groupBy: { type: String, required: true },
  mode: { type: String, required: true },
  normMode: { type: String, required: true },
})
const emit = defineEmits([
  'update:metric',
  'update:metric2',
  'update:period',
  'update:mode',
  'update:normMode',
  'swap',
])

const NORM_MODES = [
  { value: 'default', label: 'Target: median' },
  { value: 'manual', label: 'Target: manual' },
]
const PERIODS = [
  { value: 'day', label: 'Daily' },
  { value: 'week', label: 'Weekly' },
  { value: 'month', label: 'Monthly' },
]
const MODES = [
  { value: 'row', label: 'By row' },
  { value: 'table', label: 'Whole table' },
]
</script>

<template>
  <div class="mb-md flex flex-wrap items-center gap-sm">
    <div class="hm-metrics">
      <select
        class="ui-select ui-select--sm phone:w-full"
        :value="metric"
        aria-label="Primary metric"
        @change="emit('update:metric', $event.target.value)"
      >
        <optgroup v-for="group in METRIC_GROUPS" :key="group.label" :label="group.label">
          <option v-for="option in group.metrics" :key="option.key" :value="option.key">
            {{ metricLabel(option) }}
          </option>
        </optgroup>
      </select>

      <button
        type="button"
        class="ui-trigger ui-trigger--icon"
        :disabled="!metric2"
        title="Swap metrics"
        aria-label="Swap metrics"
        @click="emit('swap')"
      >
        ⇄
      </button>

      <select
        class="ui-select ui-select--sm hm-metrics__second phone:w-full"
        :value="metric2 ?? ''"
        aria-label="Second metric"
        @change="emit('update:metric2', $event.target.value || null)"
      >
        <option value="">{{ metric2 ? 'No second metric' : 'Pick a metric' }}</option>
        <optgroup v-for="group in METRIC_GROUPS" :key="group.label" :label="group.label">
          <option
            v-for="option in group.metrics"
            :key="option.key"
            :value="option.key"
            :disabled="option.key === metric"
          >
            {{ metricLabel(option) }}
          </option>
        </optgroup>
      </select>
    </div>

    <div class="ml-auto flex flex-wrap items-center gap-sm phone:ml-0 phone:w-full">
      <select
        class="ui-select ui-select--sm phone:w-full"
        :value="normMode"
        aria-label="Target source"
        @change="emit('update:normMode', $event.target.value)"
      >
        <option
          v-for="option in NORM_MODES"
          :key="option.value"
          :value="option.value"
          :disabled="option.value === 'manual' && groupBy !== 'sku'"
        >
          {{ option.label }}
        </option>
      </select>
      <select
        class="ui-select ui-select--sm phone:w-full"
        :value="period"
        aria-label="Column period"
        @change="emit('update:period', $event.target.value)"
      >
        <option v-for="option in PERIODS" :key="option.value" :value="option.value">
          {{ option.label }}
        </option>
      </select>
      <select
        class="ui-select ui-select--sm phone:w-full"
        :value="mode"
        aria-label="Color comparison"
        title="By row: each row is compared with itself. Whole table: every row on one scale."
        @change="emit('update:mode', $event.target.value)"
      >
        <option v-for="option in MODES" :key="option.value" :value="option.value">
          {{ option.label }}
        </option>
      </select>
    </div>
  </div>
</template>
