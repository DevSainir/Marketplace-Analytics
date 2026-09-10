<script setup>
/**
 * The rotation as a line: which photo stood when, for how long, and what it got.
 *
 * This block used to be a status panel — the live photo, a bar counting its
 * slot down, and three sentences explaining why the bar being full is not the
 * swap. All of that answered «что происходит прямо сейчас», which is one line
 * of text and now sits under the figures in «Итог по тесту». What no screen
 * answered was «что уже произошло», and the log below the results only answers
 * it as a table: to see that photo 3 stood nine minutes while its neighbours
 * stood an hour, you had to read a column and do the subtraction.
 *
 * A timeline shows exactly that without reading anything. Turn widths are
 * proportional, so an interrupted slot is a short segment, and a photo that got
 * two turns in one lap is two segments. The arithmetic lives in
 * `@/modules/abTests/timeline` — including why a very short turn is drawn wider
 * than its share.
 *
 * One line is one lap, and the picker opens on «Все круги», where the laps run
 * end to end on the same track. That is the view that answers the question the
 * page exists for: whether a photo was ahead in every lap or in one.
 *
 * The popup is teleported to `<body>`, for the reason `MetricHint` records: an
 * element that must escape a card has to leave the card, not out-rank it.
 */
import { computed, onUnmounted, ref } from 'vue'

import { buildTimeline, roundsIn } from '@/modules/abTests/timeline'

const props = defineProps({
  /** The open test, as the detail endpoint returns it. */
  test: { type: Object, required: true },
  /** variant_id -> object URL for the stored original. */
  imageUrls: { type: Object, default: () => ({}) },
})

// The open turn is measured to this clock; a minute is well inside the five
// minutes the rotation itself sleeps, and it keeps the live segment growing
// without a request.
const now = ref(Date.now())
const ticking = setInterval(() => (now.value = Date.now()), 60_000)
onUnmounted(() => clearInterval(ticking))

/** Which lap the line shows; 0 is «Все круги». */
const round = ref(0)

const rounds = computed(() => roundsIn(props.test.history))

const line = computed(() =>
  buildTimeline(props.test.history, { now: now.value, round: round.value }),
)

const hovered = ref(null)
const tipAt = ref({ top: 0, left: 0 })

const tipStyle = computed(() => ({ top: `${tipAt.value.top}px`, left: `${tipAt.value.left}px` }))

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

function count(value) {
  return Number(value ?? 0).toLocaleString('ru-RU')
}

/** Comma for the decimal mark, as the WB cabinet writes it. */
function percent(value) {
  if (value === null || value === undefined) return '—'
  return `${Number(value).toLocaleString('ru-RU', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}%`
}

/**
 * «08.09, 12:05 МСК».
 *
 * Moscow, spelled out, because WB operates in Moscow time and the seller reads
 * these next to figures from the WB cabinet — the same rule «История действий»
 * follows.
 *
 * @param {number|null} ms Epoch milliseconds.
 * @returns {string} The stamp, or «—».
 */
function moment(ms) {
  if (ms === null || ms === undefined) return '—'
  return `${new Date(ms).toLocaleString('ru-RU', {
    timeZone: 'Europe/Moscow',
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })} МСК`
}

/** `Хч Ym`, or minutes alone under an hour — a lap may run for days. */
function duration(ms) {
  const minutes = Math.round(Math.max(0, ms ?? 0) / 60_000)
  const hours = Math.floor(minutes / 60)
  const days = Math.floor(hours / 24)
  if (days) return `${days} д ${hours % 24} ч`
  if (hours) return `${hours} ч ${minutes % 60} мин`
  return `${minutes} мин`
}
</script>

<template>
  <section
    class="mb-lg rounded-card bg-surface p-lg shadow-card phone:p-md"
    aria-label="Ход теста"
    data-testid="rotation-timeline"
  >
    <header class="mb-lg flex flex-wrap items-center justify-between gap-md">
      <h2 class="text-base font-semibold text-primary">Ход теста</h2>
      <label v-if="rounds.length" class="flex items-center gap-sm text-tiny text-muted">
        <span>Круг</span>
        <select v-model.number="round" class="ui-select" data-testid="timeline-round">
          <option :value="0">Все круги</option>
          <option v-for="option in rounds" :key="option" :value="option">{{ option }}</option>
        </select>
      </label>
    </header>

    <div v-if="line.segments.length" class="ab-timeline">
      <div class="ab-timeline__ends">
        <span data-testid="timeline-start">{{ moment(line.startMs) }}</span>
        <span data-testid="timeline-end">{{ line.live ? 'сейчас' : moment(line.endMs) }}</span>
      </div>

      <div class="ab-timeline__track">
        <button
          v-for="segment in line.segments"
          :key="segment.key"
          type="button"
          class="ab-timeline__segment"
          :class="{ 'ab-timeline__segment--live': segment.open }"
          :style="{ left: `${segment.leftPercent}%`, width: `${segment.widthPercent}%` }"
          :aria-label="`${segment.label}: ${duration(segment.durationMs)}`"
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

      <div class="ab-timeline__labels">
        <template v-for="segment in line.segments" :key="`label-${segment.key}`">
          <div
            v-if="segment.labelled"
            class="ab-timeline__label"
            :style="{ left: `${segment.leftPercent}%` }"
          >
            <img
              v-if="imageUrls[segment.variantId]"
              :src="imageUrls[segment.variantId]"
              :alt="segment.label"
              class="ab-timeline__thumb"
            />
            <div v-else class="ab-timeline__thumb ab-timeline__thumb--empty"></div>
            <span class="ab-timeline__caption">{{ segment.label }}</span>
          </div>
        </template>
      </div>

      <p class="ab-timeline__total" data-testid="timeline-total">
        Всего {{ duration(line.totalMs) }}
      </p>
    </div>

    <p v-else class="text-tiny text-muted">
      Пока ни одной установки. Первая появится, когда тест запустится.
    </p>
  </section>

  <Teleport to="body">
    <div v-if="hovered" class="ab-timeline__tip" role="tooltip" :style="tipStyle">
      <p class="ab-timeline__tip-title">{{ hovered.label }} · круг {{ hovered.round }}</p>
      <dl class="ab-timeline__tip-rows">
        <dt>Установлено</dt>
        <dd>{{ moment(hovered.startMs) }}</dd>
        <dt>{{ hovered.open ? 'Стоит' : 'Снято' }}</dt>
        <dd>{{ hovered.open ? 'на карточке' : moment(hovered.endMs) }}</dd>
        <dt>Длительность</dt>
        <dd>{{ duration(hovered.durationMs) }}</dd>
        <dt>Показы</dt>
        <dd>{{ count(hovered.views) }}</dd>
        <dt>Клики</dt>
        <dd>{{ count(hovered.clicks) }}</dd>
        <dt>CTR</dt>
        <dd>{{ percent(hovered.clickThrough) }}</dd>
      </dl>
    </div>
  </Teleport>
</template>

<style scoped src="@/modules/abTests/components/styles/RotationTimeline.css"></style>
