<script setup>
/**
 * What one turn of the rotation did, shown while the cursor is on its segment.
 *
 * The figures here exist nowhere else at this granularity — the result table
 * sums a photo's turns and the log lists them without their length — so the
 * popup is the only place "this photo stood for nine minutes and collected 150
 * impressions" is readable at all.
 *
 * Teleported to `<body>`, for the reason `core/components/InfoHint` records: an element that
 * must escape a card has to leave the card, not out-rank it. The parent
 * measures the segment and passes viewport coordinates.
 */
import { computed } from 'vue'

import { formatNumber, formatPercent } from '@/core/utils/format'

import { formatDuration, formatStamp } from '@/modules/abTests/timeline'

const props = defineProps({
  /** The hovered turn, as `buildTimeline` shapes it. */
  turn: { type: Object, required: true },
  /** Viewport coordinates of the segment's top-left corner. */
  at: { type: Object, required: true },
})

const style = computed(() => ({ top: `${props.at.top}px`, left: `${props.at.left}px` }))

/** Label and value, in the order the questions are asked. */
const rows = computed(() => [
  { key: 'from', label: 'Installed', value: moment(props.turn.startMs) },
  {
    key: 'to',
    label: props.turn.open ? 'Now' : 'Taken off',
    value: props.turn.open ? 'on the card' : moment(props.turn.endMs),
  },
  { key: 'for', label: 'Duration', value: formatDuration(props.turn.durationMs) },
  { key: 'views', label: 'Impressions', value: formatNumber(props.turn.views) },
  { key: 'clicks', label: 'Clicks', value: formatNumber(props.turn.clicks) },
  { key: 'ctr', label: 'CTR', value: formatPercent(props.turn.clickThrough) },
])

function moment(ms) {
  const { date, time } = formatStamp(ms)
  return time ? `${date}, ${time}` : date
}
</script>

<template>
  <Teleport to="body">
    <div class="ab-tiptime" role="tooltip" :style="style">
      <p class="ab-tiptime__title">{{ turn.label }} · round {{ turn.round }}</p>
      <dl class="ab-tiptime__rows">
        <template v-for="row in rows" :key="row.key">
          <dt>{{ row.label }}</dt>
          <dd>{{ row.value }}</dd>
        </template>
      </dl>
    </div>
  </Teleport>
</template>

<style scoped src="@/modules/abTests/components/styles/TimelineTip.css"></style>
