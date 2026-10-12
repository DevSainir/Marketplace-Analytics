<script setup>
/**
 * One quiet line under the P&L header saying why the statement stops where it
 * does — «Последний еженедельный отчёт WB: 10–16 авг · ежедневные — по 18 авг».
 *
 * Dumb by design: every decision about wording, staleness and tone lives in
 * `reportFreshness.js`, which is pure and tested. This renders the result and
 * nothing else, and renders nothing at all when there is nothing honest to say.
 *
 * The clock is a `ref` rather than a bare `new Date()` so a page left open
 * overnight still turns the line into a warning once the last check is a day
 * old — a frozen clock would recreate the staleness it exists to report.
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import InfoHint from '@/core/components/InfoHint.vue'
import { describeFreshness } from '@/modules/finreports/reportFreshness'

const props = defineProps({
  /** `GET /v1/finreports/harvest`, or `null` when it could not be fetched. */
  state: { type: Object, default: null },
})

/** How often staleness is re-judged. */
const TICK_MS = 60000

const now = ref(new Date())
let timer = null

onMounted(() => {
  timer = setInterval(() => {
    now.value = new Date()
  }, TICK_MS)
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})

const line = computed(() => describeFreshness(props.state, now.value))
</script>

<template>
  <div v-if="line" class="flex flex-col gap-xs text-tiny">
    <p :class="line.tone === 'warning' ? 'text-status-warning' : 'text-muted'">
      {{ line.text }}
    </p>
    <p v-for="note in line.notes" :key="note.text" class="text-muted">
      {{ note.text }}<InfoHint v-if="note.hint" :text="note.hint" />
    </p>
  </div>
</template>
