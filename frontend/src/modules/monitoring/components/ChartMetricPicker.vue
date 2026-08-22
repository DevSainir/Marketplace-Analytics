<script setup>
/**
 * The controls above «Общий» — the one chart with no fixed question.
 *
 * Every other slide is a saved answer: its metrics were chosen because they
 * explain each other. This one is for the question nobody anticipated, and the
 * research on multi-metric charts says three things about how to offer that
 * without producing an unreadable plot.
 *
 * **A cap.** Dashboard guidance puts the readable ceiling at four to six lines,
 * after which the advice is to facet rather than keep stacking; Google's own
 * metric-comparison view compares exactly two. So the picker stops at four and
 * says so, instead of letting seventeen chips build a hairball.
 *
 * **Grouped by unit.** Metrics sharing a unit share an axis — that is what
 * keeps them comparable, and also why «Заказы, ₽» flattens «Затраты, ₽».
 * Grouping the chips under «₽ · шт · %» makes the axis behaviour visible
 * BEFORE the click rather than surprising after it.
 *
 * **A mode.** Rebasing everything to 100 at the first day is the documented
 * answer to comparing unlike scales; it is offered, never forced, because the
 * baseline day is arbitrary and a different one draws a different chart.
 *
 * Dumb by contract: choices in, selection and mode out.
 */
import { computed } from 'vue'

import { MAX_OVERVIEW_METRICS, OVERVIEW_MODES } from '@/modules/monitoring/chartSpecs'

const props = defineProps({
  /** @type {Array<{key: string, name: string, unit: string}>} */
  choices: { type: Array, required: true },
  /** Selected metric keys, in the order they were ticked. */
  modelValue: { type: Array, default: () => [] },
  /** `absolute` (real values, an axis per unit) or `index` (rebased to 100). */
  mode: { type: String, default: 'absolute' },
})

const emit = defineEmits(['update:modelValue', 'update:mode'])

/** Chips grouped under the unit whose axis they will share. */
const UNIT_TITLES = { currency: 'Рубли', number: 'Штуки', percent: 'Проценты' }
const groups = computed(() =>
  ['currency', 'number', 'percent']
    .map((unit) => ({
      unit,
      title: UNIT_TITLES[unit],
      items: props.choices.filter((choice) => choice.unit === unit),
    }))
    .filter((group) => group.items.length),
)

const full = computed(() => props.modelValue.length >= MAX_OVERVIEW_METRICS)

/** Toggle one metric, refusing to add past the cap. */
function toggle(key) {
  if (props.modelValue.includes(key)) {
    emit(
      'update:modelValue',
      props.modelValue.filter((entry) => entry !== key),
    )
    return
  }
  if (!full.value) emit('update:modelValue', [...props.modelValue, key])
}
</script>

<template>
  <div class="mt-sm">
    <div class="flex flex-wrap items-center justify-between gap-sm">
      <p class="text-tiny text-muted">
        Метрики с одной единицей делят шкалу — поэтому «Заказы, ₽» и «Затраты, ₽» вместе сплющивают
        меньшую. Режим «Индекс» приводит всё к 100 в первый день и сравнивает форму.
      </p>
      <div class="flex shrink-0 gap-xs">
        <button
          v-for="option in OVERVIEW_MODES"
          :key="option.key"
          type="button"
          :aria-pressed="mode === option.key"
          class="rounded-btn px-sm py-1 text-tiny font-medium transition"
          :class="
            mode === option.key
              ? 'bg-action text-white'
              : 'text-muted hover:bg-hover hover:text-primary'
          "
          @click="emit('update:mode', option.key)"
        >
          {{ option.label }}
        </button>
      </div>
    </div>

    <div class="mt-sm flex flex-wrap gap-md">
      <div v-for="group in groups" :key="group.unit" class="min-w-0">
        <p class="mb-xs text-micro font-medium uppercase tracking-wide text-muted">
          {{ group.title }}
        </p>
        <ul class="flex flex-wrap gap-xs">
          <li v-for="choice in group.items" :key="choice.key">
            <button
              type="button"
              :aria-pressed="modelValue.includes(choice.key)"
              :disabled="full && !modelValue.includes(choice.key)"
              class="rounded-btn border px-sm py-1 text-tiny font-medium transition disabled:cursor-not-allowed disabled:opacity-40"
              :class="
                modelValue.includes(choice.key)
                  ? 'border-action bg-action text-white'
                  : 'border-border-subtle text-muted hover:bg-hover hover:text-primary'
              "
              @click="toggle(choice.key)"
            >
              {{ choice.name }}
            </button>
          </li>
        </ul>
      </div>
    </div>

    <p v-if="full" class="mt-xs text-tiny text-muted">
      Больше {{ MAX_OVERVIEW_METRICS }} метрик на одном графике не читается — снимите одну, чтобы
      добавить другую.
    </p>
    <p v-if="!modelValue.length" class="py-xl text-center text-base text-muted">
      Выберите метрики, которые хотите сравнить на одном графике.
    </p>
  </div>
</template>
