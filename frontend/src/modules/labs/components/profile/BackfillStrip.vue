<script setup>
/**
 * «Загружаем историю» — the four lanes of a new workspace's backfill.
 *
 * A labs copy of the profile module's panel: same endpoint, same polling rule
 * (stop when nothing is moving), same reason for showing LANES rather than one
 * bar — WB serves history at three very different speeds and a combined bar
 * would sit under 15% for most of a day and be wrong about all four.
 *
 * What changed is the shape. It is a strip of four columns inside «Обзор»
 * rather than a full-width block of its own, because on the new layout it is
 * one fact among several rather than the only thing on the screen.
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { fetchBackfillStatus } from '@/modules/labs/profileApi'

const props = defineProps({
  workspaceId: { type: String, required: true },
})

/** How often to re-ask while something is still moving. */
const POLL_MS = 15000

const lanes = ref([])
const active = ref(false)
const loaded = ref(false)
let timer = null

const visible = computed(
  () => loaded.value && (active.value || lanes.value.some((lane) => lane.state === 'failed')),
)

function toneFor(state) {
  if (state === 'failed') return 'is-bad'
  if (state === 'done') return 'is-ok'
  return ''
}

async function poll() {
  try {
    const status = await fetchBackfillStatus(props.workspaceId)
    lanes.value = status.lanes
    active.value = status.active
  } catch {
    // A failed poll is not worth a banner: the backfill runs server-side
    // whatever this panel reads, and the next tick re-asks.
    return
  } finally {
    loaded.value = true
  }
  if (!active.value) stop()
}

function stop() {
  if (timer !== null) {
    clearInterval(timer)
    timer = null
  }
}

onMounted(async () => {
  await poll()
  if (active.value) timer = setInterval(poll, POLL_MS)
})

onBeforeUnmount(stop)
</script>

<template>
  <section v-if="visible" class="lp-backfill">
    <header class="lp-backfill__head">
      <h3 class="lp-backfill__title">Загружаем историю Wildberries</h3>
      <p class="lp-backfill__note">
        Это происходит один раз, само — нажимать ничего не нужно. Финансовые отчёты WB отдаёт
        медленнее остального.
      </p>
    </header>

    <ul class="lp-backfill__lanes">
      <li v-for="lane in lanes" :key="lane.lane" class="lp-lane">
        <span class="lp-lane__top">
          <span class="lp-lane__name">{{ lane.label }}</span>
          <span class="lp-lane__state" :class="toneFor(lane.state)">
            {{
              lane.state === 'done'
                ? 'готово'
                : lane.state === 'failed'
                  ? 'ошибка'
                  : `${lane.percent ?? 0}%`
            }}
          </span>
        </span>
        <span class="lp-lane__track">
          <span
            class="lp-lane__fill"
            :class="toneFor(lane.state)"
            :style="{ width: `${lane.percent ?? 4}%` }"
          />
        </span>
        <span class="lp-lane__msg">{{ lane.message }}</span>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.lp-backfill {
  @apply flex flex-col gap-md rounded-card px-lg py-md;
  background: var(--ui-surface);
  box-shadow: var(--ui-sh-xs);
}

.lp-backfill__title {
  @apply text-h3 font-semibold text-primary;
}

.lp-backfill__note {
  @apply mt-xs text-tiny font-medium;
  color: var(--ui-muted);
}

.lp-backfill__lanes {
  @apply grid gap-md;
  grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr));
}

.lp-lane {
  @apply flex flex-col gap-xs;
}

.lp-lane__top {
  @apply flex items-baseline justify-between gap-sm;
}

.lp-lane__name {
  @apply text-base font-medium text-primary;
}

.lp-lane__state {
  @apply text-tiny font-semibold tabular-nums;
  color: var(--ui-muted);
}

.lp-lane__state.is-ok {
  color: var(--ui-pos);
}

.lp-lane__state.is-bad {
  color: var(--ui-neg);
}

.lp-lane__track {
  @apply block h-1 w-full overflow-hidden rounded-btn;
  background: var(--ui-sunk);
}

.lp-lane__fill {
  @apply block h-full rounded-btn;
  background: var(--ui-action);
  transition: width var(--ui-base) var(--ui-ease);
}

.lp-lane__fill.is-ok {
  background: var(--ui-pos);
}

.lp-lane__fill.is-bad {
  background: var(--ui-neg);
}

.lp-lane__msg {
  @apply truncate text-tiny;
  color: var(--ui-faint);
}
</style>
