<script setup>
/**
 * «Загружаем историю» — the four lanes of a new workspace's history backfill.
 *
 * A seller who has just signed up gets a working product with almost nothing in
 * it: WB serves history at three very different speeds, and the slowest of them
 * — the settlement report, at one request per fifteen minutes — takes sixteen
 * hours to fill a large account's P&L. Without this panel that hour-to-day gap
 * looks exactly like a broken import, which is the reading people reach for.
 *
 * So it shows LANES, not one bar. «Каталог» is done in a second, «Воронка» and
 * «Реклама» in a couple of hours, «Финансы» keeps going — and each says so in
 * its own words, from the backend, so the wording cannot drift from what the
 * task is actually doing. One combined bar would sit under 15% for most of a
 * day and be wrong about all four.
 *
 * Nobody presses anything: the backfill is enqueued when the org's credentials
 * are first stored, so this panel's only job is to report. It polls while any
 * lane is moving and stops when none is — a finished backfill leaves no timer
 * behind, and the panel hides itself entirely once every lane is done.
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import RefreshProgress from '@/core/components/RefreshProgress.vue'
import { fetchBackfillStatus } from '@/modules/profile/api'

const props = defineProps({
  /** Workspace whose backfill to report on. */
  workspaceId: { type: String, required: true },
})

/** How often to re-ask while something is still moving. */
const POLL_MS = 15000

const lanes = ref([])
const active = ref(false)
const loaded = ref(false)
let timer = null

/**
 * The panel is worth showing only while there is something to say: during the
 * walk, and for a failed lane afterwards. A workspace backfilled last month
 * should not carry a permanent «готово» block down its profile.
 */
const visible = computed(
  () => loaded.value && (active.value || lanes.value.some((lane) => lane.state === 'failed')),
)

/** Lane rows carry their own colour only for the two states worth flagging. */
function toneFor(state) {
  if (state === 'failed') return 'text-status-negative'
  if (state === 'done') return 'text-status-positive'
  return 'text-muted'
}

async function poll() {
  try {
    const status = await fetchBackfillStatus(props.workspaceId)
    lanes.value = status.lanes
    active.value = status.active
  } catch {
    // A failed poll is not worth a red banner: the backfill runs server-side
    // whatever this panel manages to read, and the next tick re-asks. Stopping
    // the timer here would be the actual harm — a transient 502 during a deploy
    // would freeze the panel for the rest of the session.
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
  <section
    v-if="visible"
    class="rounded-card border border-border-subtle bg-surface p-lg shadow-card"
  >
    <h2 class="text-h2 font-bold text-primary">Загружаем историю Wildberries</h2>
    <p class="mt-xs text-small text-muted">
      Это происходит один раз, само — ничего нажимать не нужно. Каталог и воронка появятся в течение
      пары часов, финансовые отчёты Wildberries отдаёт медленнее.
    </p>

    <ul class="mt-lg flex flex-col gap-md">
      <li
        v-for="lane in lanes"
        :key="lane.lane"
        class="flex flex-col gap-xs phone:gap-sm sm:flex-row sm:items-center sm:justify-between"
      >
        <div class="flex items-baseline gap-sm">
          <span class="text-base font-medium text-primary">{{ lane.label }}</span>
          <span :class="['text-tiny font-medium', toneFor(lane.state)]">
            {{ lane.state === 'done' ? 'готово' : lane.state === 'failed' ? 'ошибка' : '' }}
          </span>
        </div>
        <RefreshProgress :percent="lane.percent" :message="lane.message" />
      </li>
    </ul>
  </section>
</template>
