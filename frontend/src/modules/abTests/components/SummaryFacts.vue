<script setup>
/**
 * The standing facts about a run: which photo is up, when it started and
 * stopped, how much of that was measured, and how far round the rotation is.
 *
 * One row, photo first. These are the same kind of statement — a fact about the
 * test rather than a figure it produced — and stacked in three blocks they read
 * as three sections, two of which are one line long. Side by side with the ends
 * pushed apart they read as the caption they are.
 *
 * «Длительность» is the summed length of the measured intervals, NOT wall clock
 * since the start. The two used to sit together and dropping the wall clock is
 * what makes it possible to misread this one: nine hours of data inside a
 * fourteen-hour test has to keep saying nine. The difference is idle time, and
 * «Остановлен» says that outright, with a date on it.
 */
import { computed } from 'vue'

import MetricHint from '@/modules/abTests/components/MetricHint.vue'

const props = defineProps({
  /** The open test, as the detail endpoint returns it. */
  test: { type: Object, required: true },
  /** Its `summary` block, already defaulted by the parent. */
  summary: { type: Object, default: () => ({}) },
  /** variant_id -> object URL for the stored original. */
  imageUrls: { type: Object, default: () => ({}) },
})

const measuredMs = computed(() => Number(props.summary.measured_minutes ?? 0) * 60_000)

/** When it started, when it stopped, and how much of that was measured. */
const facts = computed(() => [
  { key: 'started', label: 'Запущен', value: moment(props.test.started_at) },
  {
    key: 'stopped',
    label: 'Остановлен',
    value: moment(props.test.stopped_at),
    hint: 'Когда ротация прекратилась — пауза считается наравне с завершением.',
  },
  {
    key: 'measured',
    label: 'Длительность',
    value: duration(measuredMs.value),
    hint: 'Сумма длительностей отрезков. Паузы и часы без работающей рекламы в неё не входят.',
  },
])

/** «3 фото из 8 успели набрать показы» — how much of the test has run at all. */
const coverage = computed(() => ({
  measured: Number(props.summary.variants_measured ?? 0),
  total: Number(props.summary.variants_total ?? 0),
  rounds: Number(props.summary.rounds_completed ?? 0),
}))

const active = computed(() =>
  (props.test.variants ?? []).find(
    (variant) => variant.variant_id === props.test.active_variant_id,
  ),
)

/** «Главное» for the baseline, «Вариант N» for a candidate. */
const activeLabel = computed(() => {
  if (!active.value) return ''
  return active.value.is_original ? 'Главное' : `Вариант ${active.value.position}`
})

function moment(value) {
  const parsed = Date.parse(value ?? '')
  if (Number.isNaN(parsed)) return '—'
  return new Date(parsed).toLocaleString('ru-RU', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** `Хч Ym`, or minutes alone under an hour — a test may run for days. */
function duration(ms) {
  if (ms === null || ms === undefined) return '—'
  const minutes = Math.floor(ms / 60_000)
  const hours = Math.floor(minutes / 60)
  const days = Math.floor(hours / 24)
  if (days) return `${days} д ${hours % 24} ч`
  if (hours) return `${hours} ч ${minutes % 60} мин`
  return `${minutes} мин`
}
</script>

<template>
  <div
    class="mt-lg flex flex-wrap items-center justify-between gap-x-lg gap-y-md border-t border-border-subtle pt-md"
  >
    <div v-if="active" class="flex items-center gap-md" data-testid="summary-live-photo">
      <img
        v-if="imageUrls[active.variant_id]"
        :src="imageUrls[active.variant_id]"
        :alt="activeLabel"
        class="ab-summary__photo"
      />
      <div v-else class="ab-summary__photo ab-summary__photo--empty"></div>
      <div class="min-w-0">
        <p class="text-base font-semibold text-primary">Сейчас на карточке</p>
        <p class="text-tiny font-semibold text-action">{{ activeLabel }}</p>
      </div>
    </div>

    <dl class="flex flex-wrap gap-x-lg gap-y-sm">
      <div v-for="fact in facts" :key="fact.key" class="flex items-baseline gap-xs">
        <dt class="text-tiny text-muted">{{ fact.label }}</dt>
        <dd
          class="text-tiny font-semibold tabular-nums text-primary"
          :data-testid="`fact-${fact.key}`"
        >
          {{ fact.value }}
        </dd>
        <MetricHint v-if="fact.hint" :text="fact.hint" />
      </div>
    </dl>

    <p class="text-tiny text-muted">
      Показы набрали {{ coverage.measured }} фото из {{ coverage.total }}; кругов пройдено
      {{ coverage.rounds }}.
    </p>
  </div>
</template>

<style scoped>
/* 3:4 is WB's own card aspect; small, because this is a caption under the
   figures rather than the subject of the block. */
.ab-summary__photo {
  width: 60px;
  height: 80px;
  flex: none;
  object-fit: cover;
  border-radius: var(--ui-r-md);
  box-shadow: var(--ui-sh-sm);
}

.ab-summary__photo--empty {
  background: var(--ui-sunk);
}
</style>
