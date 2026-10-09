<script setup>
/**
 * The rotation as a line: which photo stood when, for how long, and what it got.
 *
 * This block used to be a status panel — the live photo and a bar counting its
 * slot down. All of that answered «что происходит прямо сейчас», which is one
 * line of text and now sits in «Итог по тесту». What no screen answered was
 * «что уже произошло»: to see that photo 3 stood nine minutes while its
 * neighbours stood an hour you had to read a column of the log and subtract.
 *
 * A timeline shows that without reading anything. Widths are proportional, so
 * an interrupted slot is a short segment and a photo dealt twice in a lap is
 * two of them. The arithmetic is in `@/modules/abTests/timeline`, including why
 * a very short turn is drawn wider than its share.
 *
 * One line is one lap, and the picker opens on «Все круги», where the laps run
 * end to end on one track — the view that answers whether a photo led every lap
 * or only one.
 *
 * A second picker appears beside it when more than one campaign paid for the
 * traffic. Choosing one narrows the line to the turns THAT campaign measured:
 * a campaign switched off during the fourth lap draws four laps, not ten with
 * six blanks. The two filters compose, because «третий круг единой ставки» is
 * a question and either half alone is a different one.
 *
 * That view has no upper bound: ten photos over ten laps is a hundred turns, and
 * no amount of proportion fits a hundred thumbnails across a card. Past the
 * point where each turn has room for its own marker the line **scrolls
 * sideways** instead of compressing, at a fixed width per turn — the block keeps
 * its height and its meaning, and the reader pans through the test rather than
 * squinting at it. A line that fits keeps fitting; nothing scrolls until it has
 * to.
 *
 * The popup is teleported to `<body>`, for the reason `core/components/InfoHint` records: an
 * element that must escape a card has to leave the card, not out-rank it.
 */
import { computed, onUnmounted, ref, watch } from 'vue'

import BlockFilters from '@/modules/abTests/components/BlockFilters.vue'
import TimelineMarkers from '@/modules/abTests/components/TimelineMarkers.vue'
import TimelineTip from '@/modules/abTests/components/TimelineTip.vue'
import {
  buildTimeline,
  formatDuration,
  formatStamp,
  roundsIn,
  trackSize,
} from '@/modules/abTests/timeline'

const props = defineProps({
  /** The open test, as the detail endpoint returns it. */
  test: { type: Object, required: true },
  /** variant_id -> object URL for the stored original. */
  imageUrls: { type: Object, default: () => ({}) },
})

// The live turn is measured to this clock; a minute is well inside the five
// minutes the rotation itself sleeps, and it keeps the live segment growing
// without a request.
const now = ref(Date.now())
const ticking = setInterval(() => (now.value = Date.now()), 60_000)
onUnmounted(() => clearInterval(ticking))

/** Which lap the line shows; 0 is «Все круги». */
const round = ref(0)

/** Which campaign the line shows; 0 is «Все». */
const campaign = ref(0)

/** The campaigns that brought traffic — the picker exists only past one. */
const campaigns = computed(() => props.test.campaigns ?? [])

const rounds = computed(() => roundsIn(props.test.history, campaign.value))

// A lap the chosen campaign never ran would leave the line empty and the
// picker pointing at nothing, so the filter falls back to «Все круги» rather
// than showing a blank block.
watch(rounds, (available) => {
  if (round.value && !available.includes(round.value)) round.value = 0
})

/**
 * Where the line stops.
 *
 * A pause leaves the photo on the card, so its exposure is never closed — and
 * measuring it to «сейчас» drew a striped segment that grew for as long as the
 * test stood, squeezing every turn that actually happened into the left edge.
 * The rotation stopped when the test did, and that is where the line ends.
 *
 * The last fallback is for a test paused before `stopped_at` existed: the end
 * of the last turn that did close is the latest moment the rotation is known to
 * have moved, which is a bounded guess where «сейчас» is an unbounded one.
 */
const endsAt = computed(() => {
  if (props.test.status === 'running') return now.value
  const stopped = Date.parse(props.test.stopped_at ?? props.test.finished_at ?? '')
  if (!Number.isNaN(stopped)) return stopped
  const closed = (props.test.history ?? [])
    .map((row) => Date.parse(row.deactivated_at ?? ''))
    .filter((ms) => !Number.isNaN(ms))
  return closed.length ? Math.max(...closed) : now.value
})

const line = computed(() =>
  buildTimeline(props.test.history, {
    endsAt: endsAt.value,
    round: round.value,
    campaignId: campaign.value,
  }),
)

/** Only a running test's line ends at «сейчас»; every other one ends at a time. */
const live = computed(() => props.test.status === 'running' && line.value.live)

// The markers alternate, so each row is half of them. Split here rather than
// filtered twice in the template, where the second filter is easy to get the
// wrong way round and the symptom is a row of duplicates.
const above = computed(() => line.value.segments.filter((segment) => segment.above))
const below = computed(() => line.value.segments.filter((segment) => !segment.above))

/** How wide the track is drawn, and whether its thumbnails get the large size. */
const track = computed(() => trackSize(line.value.segments.length))

const hovered = ref(null)
const tipAt = ref({ top: 0, left: 0 })

/**
 * Open the popup above the hovered segment, nudged to stay on screen.
 *
 * Measured on enter rather than followed: the page can scroll under an open
 * popup, and a listener for the two seconds anyone looks at it is not worth it.
 *
 * @param {object} segment The hovered turn.
 * @param {MouseEvent|FocusEvent} event The event carrying the target element.
 * @returns {void}
 */
function open(segment, event) {
  const rect = event.currentTarget?.getBoundingClientRect()
  if (!rect) return
  const width = Math.min(300, window.innerWidth * 0.8)
  const margin = 8
  tipAt.value = {
    top: rect.top - margin,
    left: Math.min(
      Math.max(margin, rect.left + rect.width / 2 - width / 2),
      Math.max(margin, window.innerWidth - width - margin),
    ),
  }
  hovered.value = segment
}

function close() {
  hovered.value = null
}

onUnmounted(close)
</script>

<template>
  <section
    class="mb-lg rounded-card border border-border-subtle bg-surface p-lg shadow-card phone:p-md"
    aria-label="Ход теста"
    data-testid="rotation-timeline"
  >
    <BlockFilters
      v-model:campaign="campaign"
      v-model:round="round"
      class="mb-lg"
      title="Ход теста"
      :campaigns="campaigns"
      :vendor-code="test.vendor_code ?? ''"
      :rounds="rounds"
      all-rounds-label="Все круги"
      campaign-testid="timeline-campaign"
      round-testid="timeline-round"
    />

    <div v-if="line.segments.length" class="ab-timeline__scroll">
      <div class="ab-timeline" :style="{ width: track.width }">
        <TimelineMarkers :segments="above" :image-urls="imageUrls" :large="track.large" above />
        <div class="ab-timeline__ends">
          <span class="ab-timeline__end" data-testid="timeline-start">
            <span>{{ formatStamp(line.startMs).date }}</span>
            <span>{{ formatStamp(line.startMs).time }}</span>
          </span>
          <span class="ab-timeline__end ab-timeline__end--right" data-testid="timeline-end">
            <template v-if="live">
              <span>сейчас</span>
            </template>
            <template v-else>
              <span>{{ formatStamp(line.endMs).date }}</span>
              <span>{{ formatStamp(line.endMs).time }}</span>
            </template>
          </span>
        </div>

        <div class="ab-timeline__track">
          <button
            v-for="segment in line.segments"
            :key="segment.key"
            type="button"
            class="ab-timeline__segment"
            :class="{ 'ab-timeline__segment--live': segment.open }"
            :style="{ left: `${segment.leftPercent}%`, width: `${segment.widthPercent}%` }"
            :aria-label="`${segment.label}: ${formatDuration(segment.durationMs)}`"
            data-testid="timeline-segment"
            @mouseenter="open(segment, $event)"
            @mouseleave="close"
            @focus="open(segment, $event)"
            @blur="close"
          />
          <span
            v-for="segment in line.segments"
            :key="`tick-${segment.key}`"
            class="ab-timeline__tick"
            :style="{ left: `${segment.leftPercent}%` }"
          />
          <span class="ab-timeline__tick" style="left: 100%" />
        </div>

        <TimelineMarkers :segments="below" :image-urls="imageUrls" :large="track.large" />
      </div>
    </div>

    <!-- Outside the scroller: it describes the whole line rather than a place
         on it, and centred on 5600px of track it was only readable if you
         happened to stop panning in the middle. -->
    <p v-if="line.segments.length" class="ab-timeline__total" data-testid="timeline-total">
      Всего {{ formatDuration(line.totalMs) }}
    </p>

    <p v-else class="text-tiny text-muted">
      Пока ни одной установки. Первая появится, когда тест запустится.
    </p>
  </section>

  <TimelineTip v-if="hovered" :turn="hovered" :at="tipAt" />
</template>

<style scoped src="@/modules/abTests/components/styles/RotationTimeline.css"></style>
