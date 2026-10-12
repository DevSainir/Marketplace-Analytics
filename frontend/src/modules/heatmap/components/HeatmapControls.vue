<script setup>
/**
 * The grid's own controls: what is painted, and how.
 *
 * Left: the painted metric, ⇄, and an optional second metric — when one is
 * chosen every cell carries two numbers, the painted one on top. Each select
 * is as wide as its longest option, no wider. Right: where the norm comes
 * from (the median, or a number typed per article), the column width (день /
 * неделя / месяц), and whether a row is compared with its own days or with
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
  { value: 'default', label: 'Норма: по умолчанию' },
  { value: 'manual', label: 'Норма: ручной ввод' },
]
const PERIODS = [
  { value: 'day', label: 'По дням' },
  { value: 'week', label: 'По неделям' },
  { value: 'month', label: 'По месяцам' },
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
