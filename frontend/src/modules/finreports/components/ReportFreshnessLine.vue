<script setup>
/**
 * One quiet line under the P&L header saying why the statement stops where it
 * does — «Последний отчёт WB: 10–16 авг · загружен 18 авг, 06:14 · Wildberries
 * пока не опубликовал отчёт новее 10–16 авг · проверено 12 мин назад».
 *
 * Dumb by design: every decision about wording, elapsed time and tone lives in
 * `reportFreshness.js`, which is pure and tested. This renders the result and
 * nothing else, and renders nothing at all when there is nothing honest to say.
 *
 * The clock is a `ref` rather than a bare `new Date()` so «12 мин назад» does
 * not sit frozen on a page left open all afternoon — which would recreate, in
 * the line itself, the staleness it exists to report.
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { describeFreshness } from '@/modules/finreports/reportFreshness'

const props = defineProps({
  /** `GET /v1/finreports/harvest`, or `null` when it could not be fetched. */
  state: { type: Object, default: null },
})

/** How often the elapsed phrase is recomputed. Minute resolution, minute tick. */
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
  <p
    v-if="line"
    class="text-tiny"
    :class="line.tone === 'warning' ? 'text-status-warning' : 'text-muted'"
  >
    {{ line.text }}
  </p>
</template>
