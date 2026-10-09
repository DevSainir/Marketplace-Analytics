<script setup>
/**
 * The grid's own controls: what is painted, and how the grid is cut.
 *
 * Left: the painted metric, ⇄, and an optional second metric — when one is
 * chosen every cell carries two numbers, the painted one on top. Each select
 * is as wide as its longest option, no wider. Right: where the norm comes
 * from (the median, or a number typed per article), the column width (день /
 * неделя / месяц), what a row stands for, and whether a row is compared with
 * its own days or with every other row.
 *
 * Native selects, as everywhere in this app: they are the accessible picker on
 * a phone, and the list of twenty-five metrics is exactly what one is for.
 */
import { computed } from 'vue'

import { METRIC_GROUPS, metricLabel } from '@/modules/heatmap/metrics'

const props = defineProps({
  metric: { type: String, required: true },
  metric2: { type: String, default: null },
  period: { type: String, required: true },
  groupBy: { type: String, required: true },
  mode: { type: String, required: true },
  normMode: { type: String, required: true },
  /** Whether the settlement's money metrics are offered — the P&L grant. */
  finance: { type: Boolean, default: true },
})
const emit = defineEmits([
  'update:metric',
  'update:metric2',
  'update:period',
  'update:groupBy',
  'update:mode',
  'update:normMode',
  'swap',
])

/** The picker's groups, without the money a caller has no P&L grant for. */
const groups = computed(() =>
  props.finance
    ? METRIC_GROUPS
    : METRIC_GROUPS.filter((group) => group.metrics.every((metric) => !metric.settled)),
)

const NORM_MODES = [
  { value: 'default', label: 'Норма: по умолчанию' },
  { value: 'manual', label: 'Норма: ручной ввод' },
]
const PERIODS = [
  { value: 'day', label: 'По дням' },
  { value: 'week', label: 'По неделям' },
  { value: 'month', label: 'По месяцам' },
]
/** What a row is — chips, worded as advertising and the summary word the same cut. */
const CUTS = [
  { value: 'sku', label: 'Артикулы' },
  { value: 'subject', label: 'Предметы' },
  { value: 'brand', label: 'Бренды' },
  { value: 'group', label: 'Группы' },
]
const MODES = [
  { value: 'row', label: 'По строке' },
  { value: 'table', label: 'По всей таблице' },
]
</script>

<template>
  <div class="mb-md flex flex-wrap items-center gap-sm">
    <div class="hm-metrics">
      <select
        class="ui-select ui-select--sm phone:w-full"
        :value="metric"
        aria-label="Основная метрика"
        @change="emit('update:metric', $event.target.value)"
      >
        <optgroup v-for="group in groups" :key="group.label" :label="group.label">
          <option v-for="option in group.metrics" :key="option.key" :value="option.key">
            {{ metricLabel(option) }}
          </option>
        </optgroup>
      </select>

      <button
        type="button"
        class="ui-trigger ui-trigger--icon"
        :disabled="!metric2"
        title="Поменять метрики местами"
        aria-label="Поменять метрики местами"
        @click="emit('swap')"
      >
        ⇄
      </button>

      <select
        class="ui-select ui-select--sm hm-metrics__second phone:w-full"
        :value="metric2 ?? ''"
        aria-label="Вторая метрика"
        @change="emit('update:metric2', $event.target.value || null)"
      >
        <option value="">{{ metric2 ? 'Без второй метрики' : 'Выберите метрику' }}</option>
        <optgroup v-for="group in groups" :key="group.label" :label="group.label">
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
      <div class="flex items-center gap-xs" role="group" aria-label="Строки">
        <button
          v-for="option in CUTS"
          :key="option.value"
          type="button"
          class="ui-chip"
          :class="{ 'is-on': groupBy === option.value }"
          @click="emit('update:groupBy', option.value)"
        >
          {{ option.label }}
        </button>
      </div>
      <select
        class="ui-select ui-select--sm phone:w-full"
        :value="normMode"
        aria-label="Откуда берётся норма"
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
        aria-label="Период колонок"
        @change="emit('update:period', $event.target.value)"
      >
        <option v-for="option in PERIODS" :key="option.value" :value="option.value">
          {{ option.label }}
        </option>
      </select>
      <select
        class="ui-select ui-select--sm phone:w-full"
        :value="mode"
        aria-label="Как сравнивать цвета"
        title="По строке — каждая строка сравнивается сама с собой. По всей таблице — все строки на одной шкале."
        @change="emit('update:mode', $event.target.value)"
      >
        <option v-for="option in MODES" :key="option.value" :value="option.value">
          {{ option.label }}
        </option>
      </select>
    </div>
  </div>
</template>
