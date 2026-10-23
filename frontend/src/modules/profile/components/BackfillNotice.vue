<script setup>
/**
 * One line under a page's header while a new workspace's history is still being
 * fetched from WB: "Loading history from WB — Sales funnel 40%".
 *
 * Without it a new workspace's "Summary", "Advertising" or heatmap was simply empty
 * for the day the backfill runs, which reads as "the service does not work".
 * The profile shows the full lanes (`BackfillStrip`); a page only names the
 * lanes its own figures come from — the summary does not care that the
 * funnel is still walking, the heatmap does.
 *
 * Polls while anything it names is still moving and goes quiet for good once
 * it all is done. A failed read is silent: this is a footnote, and a footnote
 * that fails must not shout over the page. That includes a refusal — see the
 * note in `BackfillStrip` on the 403 that hid this from managers until
 * 2026-10-17, and why the API's metrics rather than a console caught it.
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { fetchBackfillStatus } from '@/modules/profile/api'
import { useWorkspaceStore } from '@/modules/profile/store'

const props = defineProps({
  /** Lane keys this page's figures come from: catalogue | funnel | advertising | pnl. */
  lanes: { type: Array, required: true },
})

/** How often to re-ask while something is still moving. */
const POLL_MS = 15000

const workspaces = useWorkspaceStore()
const moving = ref([])
let timer = null

const text = computed(() => {
  if (!moving.value.length) return ''
  const parts = moving.value.map((lane) => `${lane.label} ${lane.percent ?? 0}%`)
  return `Loading history from WB — ${parts.join(', ')}. Earlier days appear as they load.`
})

function stop() {
  clearInterval(timer)
  timer = null
}

async function poll() {
  const id = workspaces.currentWorkspaceId
  if (!id) return stop()
  try {
    const status = await fetchBackfillStatus(id)
    moving.value = status.lanes.filter(
      (lane) => props.lanes.includes(lane.lane) && ['pending', 'running'].includes(lane.state),
    )
  } catch {
    return
  }
  if (!moving.value.length) stop()
}

onMounted(async () => {
  await poll()
  if (moving.value.length) timer = setInterval(poll, POLL_MS)
})
onBeforeUnmount(stop)
</script>

<template>
  <p v-if="text" class="mb-md text-tiny text-muted" role="status">{{ text }}</p>
</template>
