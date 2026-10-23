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
 * "Duration" is the summed length of the measured intervals, NOT wall clock
 * since the start. The two used to sit together and dropping the wall clock is
 * what makes it possible to misread this one: nine hours of data inside a
 * fourteen-hour test has to keep saying nine. The difference is idle time, and
 * "Stopped" says that outright, with a date on it.
 */
import { computed } from 'vue'

import InfoHint from '@/core/components/InfoHint.vue'
import { plural } from '@/core/utils/format'
import { formatMoscow } from '@/core/utils/moscow'

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
  { key: 'started', label: 'Started', value: moment(props.test.started_at) },
  {
    key: 'stopped',
    label: 'Stopped',
    value: moment(props.test.stopped_at),
    hint: 'When the rotation stopped — a pause counts the same as a finish.',
  },
  {
    key: 'measured',
    label: 'Duration',
    value: duration(measuredMs.value),
    hint: 'The measured intervals added up. Pauses and hours with no ads running are left out.',
  },
])

/** "Impressions on 3 of 8 photos" — how much of the test has run at all. */
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

/** "Main photo" for the baseline, "Variant N" for a candidate. */
const activeLabel = computed(() => {
  if (!active.value) return ''
  return active.value.is_original ? 'Main photo' : `Variant ${active.value.position}`
})

/** "14 Oct, 10:47 MSK". */
function moment(value) {
  return formatMoscow(value, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}

/** "X d Y h" or "X h Y min", or minutes alone under an hour — a test may run for days. */
function duration(ms) {
  if (ms === null || ms === undefined) return '—'
  const minutes = Math.floor(ms / 60_000)
  const hours = Math.floor(minutes / 60)
  const days = Math.floor(hours / 24)
  if (days) return `${days} d ${hours % 24} h`
  if (hours) return `${hours} h ${minutes % 60} min`
  return `${minutes} min`
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
        <p class="text-base font-semibold text-primary">On the card now</p>
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
        <InfoHint v-if="fact.hint" :text="fact.hint" />
      </div>
    </dl>

    <p class="text-tiny text-muted">
      Impressions on {{ coverage.measured }} of {{ coverage.total }}
      {{ plural(coverage.total, ['photo', 'photos']) }}; {{ coverage.rounds }}
      {{ plural(coverage.rounds, ['round', 'rounds']) }} completed.
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
