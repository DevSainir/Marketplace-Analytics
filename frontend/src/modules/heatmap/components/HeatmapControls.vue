<script setup>
/**
 * The grid's own controls: what is painted, and how the grid is cut.
 *
 * Left: the painted metric, ⇄, and an optional second metric — when one is
 * chosen every cell carries two numbers, the painted one on top. Right: the
 * column width (день / неделя / месяц), what a row stands for, and «Вид» —
 * whether a row is compared with its own days or with every other row.
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
  /** `{prices, ads: [], settlement}` from the grid, for the money metrics' names. */
  currencies: { type: Object, default: () => ({}) },
})
const emit = defineEmits([
  'update:metric',
  'update:metric2',
  'update:period',
  'update:groupBy',
  'update:mode',
  'swap',
])

const PERIODS = [
  { value: 'day', label: 'По дням' },
  { value: 'week', label: 'По неделям' },
  { value: 'month', label: 'По месяцам' },
]
const CUTS = [
  { value: 'sku', label: 'По товару' },
  { value: 'subject', label: 'По категории' },
  { value: 'brand', label: 'По бренду' },
  { value: 'group', label: 'По группе' },
]
const MODES = [
  { value: 'row', label: 'Цвет: дни одного товара' },
  { value: 'table', label: 'Цвет: товары между собой' },
]
</script>

<template>
  <div class="mb-md flex flex-wrap items-center gap-sm">
    <div class="hm-metrics">
      <select
        class="hm-select w-72"
        :value="metric"
        aria-label="Основная метрика"
        @change="emit('update:metric', $event.target.value)"
      >
        <optgroup v-for="group in METRIC_GROUPS" :key="group.label" :label="group.label">
          <option v-for="option in group.metrics" :key="option.key" :value="option.key">
            {{ metricLabel(option, currencies) }}
          </option>
        </optgroup>
      </select>

      <button
        type="button"
        class="hm-trigger hm-trigger--icon"
        :disabled="!metric2"
        title="Поменять метрики местами"
        aria-label="Поменять метрики местами"
        @click="emit('swap')"
      >
        ⇄
      </button>

      <select
        class="hm-select hm-metrics__second w-72"
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
            {{ metricLabel(option, currencies) }}
          </option>
        </optgroup>
      </select>
    </div>

    <div class="ml-auto flex flex-wrap items-center gap-sm phone:ml-0 phone:w-full">
      <select
        class="hm-select"
        :value="period"
        aria-label="Период колонок"
        @change="emit('update:period', $event.target.value)"
      >
        <option v-for="option in PERIODS" :key="option.value" :value="option.value">
          {{ option.label }}
        </option>
      </select>
      <select
        class="hm-select"
        :value="groupBy"
        aria-label="Строки"
        @change="emit('update:groupBy', $event.target.value)"
      >
        <option v-for="option in CUTS" :key="option.value" :value="option.value">
          {{ option.label }}
        </option>
      </select>
      <select
        class="hm-select"
        :value="mode"
        aria-label="Как сравнивать цвета"
        title="Дни одного товара — зелёный и красный у каждого товара свои: лучший и худший его день. Товары между собой — одна шкала на всю таблицу: сильные товары зелёные целиком, слабые красные."
        @change="emit('update:mode', $event.target.value)"
      >
        <option v-for="option in MODES" :key="option.value" :value="option.value">
          {{ option.label }}
        </option>
      </select>
    </div>
  </div>
</template>
