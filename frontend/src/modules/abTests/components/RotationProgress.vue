<script setup>
/**
 * What the rotation is doing right now: which photo is up, and how far through
 * its turn it is.
 *
 * The page used to answer none of that. You pressed «Запустить» and got a
 * status word — the table's «Сейчас на карточке» told you *which* photo, and
 * nothing told you whether anything was happening or when it would next move.
 * On a time-triggered test that is a page which looks identical for twenty
 * minutes, and the reading people reach for is «сломалось».
 *
 * Both triggers have a real denominator, so both get a bar:
 *
 * * **Time** — elapsed against `slot_minutes`, counted from `active_since`,
 *   which is when THIS photo went up rather than when the test started. Ticks
 *   locally once a second; no request is involved.
 * * **Impressions** — the live photo's own `views` against `impression_budget`.
 *   That is the same comparison the backend's trigger makes, so the bar cannot
 *   disagree with the swap. It moves only when the detail is re-read.
 *
 * The bar reaching 100 % is not the swap. The rotation is a Celery pass every
 * five minutes, so a finished slot waits for the next one — said in words
 * rather than left as a bar stuck at the end looking wedged.
 */
import { computed, onUnmounted, ref } from 'vue'

const props = defineProps({
  /** The open test, as the detail endpoint returns it. */
  test: { type: Object, required: true },
  /** variant_id -> object URL for the stored original. */
  imageUrls: { type: Object, default: () => ({}) },
})

/** How often the rotation task wakes; mirrors the beat schedule. */
const POLL_MINUTES = 5

// The clock the countdown reads. A ref rather than `Date.now()` inline,
// because a computed over a non-reactive clock never recomputes.
const now = ref(Date.now())
const ticking = setInterval(() => (now.value = Date.now()), 1000)
onUnmounted(() => clearInterval(ticking))

/** Only a live rotation has a turn in progress; a draft has nothing to show. */
const visible = computed(() => ['running', 'paused'].includes(props.test.status))

const active = computed(() =>
  (props.test.variants ?? []).find(
    (variant) => variant.variant_id === props.test.active_variant_id,
  ),
)

/** «Главное» for the captured photo, «Вариант N» for an upload. */
const activeLabel = computed(() => {
  if (!active.value) return ''
  return active.value.is_original ? 'Главное' : `Вариант ${active.value.position}`
})

/** Which turn of how many — the circle, in one line. */
const standing = computed(() => {
  const variants = props.test.variants ?? []
  const index = variants.findIndex((v) => v.variant_id === props.test.active_variant_id)
  return index < 0 ? '' : `Фото ${index + 1} из ${variants.length}`
})

const byTime = computed(() => props.test.trigger_mode === 'time')

/** Milliseconds the live photo has been up, or null before anything went up. */
const elapsedMs = computed(() => {
  if (!props.test.active_since) return null
  const started = Date.parse(props.test.active_since)
  return Number.isNaN(started) ? null : Math.max(0, now.value - started)
})

const slotMs = computed(() => Number(props.test.slot_minutes ?? 0) * 60_000)

const percent = computed(() => {
  if (byTime.value) {
    if (!slotMs.value || elapsedMs.value === null) return null
    return clamp((elapsedMs.value / slotMs.value) * 100)
  }
  const budget = Number(props.test.impression_budget ?? 0)
  if (!budget || !active.value) return null
  return clamp((Number(active.value.views ?? 0) / budget) * 100)
})

/** The figure under the bar: what is being counted, and against what. */
const measure = computed(() => {
  if (byTime.value) {
    if (elapsedMs.value === null) return 'Фото ещё не установлено'
    const left = slotMs.value - elapsedMs.value
    return left > 0
      ? `Осталось ${clock(left)} из ${count(props.test.slot_minutes)} мин`
      : 'Слот отработан'
  }
  if (!active.value) return 'Фото ещё не установлено'
  return `${count(active.value.views)} из ${count(props.test.impression_budget)} показов`
})

/**
 * Why nothing has moved although the bar is full.
 *
 * Only for the time trigger: an impression budget is only ever reached by a
 * pass that is already running, so there is no such gap to explain.
 */
const waiting = computed(
  () =>
    byTime.value && elapsedMs.value !== null && slotMs.value > 0 && elapsedMs.value >= slotMs.value,
)

function clamp(value) {
  return Math.max(0, Math.min(100, Math.round(value)))
}

function count(value) {
  return Number(value ?? 0).toLocaleString('ru-RU')
}

/** `mm:ss`, or `ч:мм:сс` past an hour — a slot may be up to two weeks. */
function clock(ms) {
  const total = Math.ceil(ms / 1000)
  const seconds = String(total % 60).padStart(2, '0')
  const minutes = Math.floor(total / 60) % 60
  const hours = Math.floor(total / 3600)
  return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${seconds}` : `${minutes}:${seconds}`
}
</script>

<template>
  <section
    v-if="visible"
    class="mb-lg rounded-card bg-surface p-lg shadow-card phone:p-md"
    aria-label="Ход ротации"
    data-testid="rotation-progress"
  >
    <div class="flex items-center gap-md">
      <img
        v-if="active && imageUrls[active.variant_id]"
        :src="imageUrls[active.variant_id]"
        :alt="activeLabel"
        class="ab-progress__photo"
      />
      <div v-else class="ab-progress__photo ab-progress__photo--empty"></div>

      <div class="min-w-0 flex-1">
        <div class="flex flex-wrap items-baseline gap-x-sm gap-y-xs">
          <span class="text-base font-semibold text-primary">Сейчас на карточке</span>
          <span v-if="activeLabel" class="text-tiny font-semibold text-action">
            {{ activeLabel }}
          </span>
          <span v-if="standing" class="text-tiny text-muted">· {{ standing }}</span>
          <span v-if="test.status === 'paused'" class="text-tiny font-semibold text-status-warning">
            · на паузе
          </span>
        </div>

        <div
          class="mt-sm h-1 w-full overflow-hidden rounded-btn bg-border-subtle"
          role="progressbar"
          :aria-valuenow="percent ?? undefined"
          aria-valuemin="0"
          aria-valuemax="100"
        >
          <!-- A resting sliver rather than an empty track: a 0 %-wide bar and
               a broken one look the same. -->
          <div
            class="h-full rounded-btn bg-action transition-[width] duration-500 ease-out"
            :style="{ width: `${percent ?? 2}%` }"
          />
        </div>

        <div class="mt-xs flex items-baseline justify-between gap-sm">
          <span class="text-tiny text-muted" data-testid="rotation-measure">{{ measure }}</span>
          <span
            v-if="percent !== null"
            class="shrink-0 text-tiny font-semibold tabular-nums text-primary"
          >
            {{ percent }}%
          </span>
        </div>
      </div>
    </div>

    <p v-if="waiting" class="mt-sm text-tiny text-muted">
      Слот отработан — фото сменится на ближайшем проходе ротации. Она просыпается раз в
      {{ POLL_MINUTES }} минут, поэтому смена происходит не ровно в ноль.
    </p>
    <p v-else-if="test.status === 'paused'" class="mt-sm text-tiny text-muted">
      На паузе фото остаётся на карточке, но время и трафик этого отрезка не засчитываются никакому
      варианту.
    </p>
  </section>
</template>

<style scoped>
/* Larger than the table's thumbnail: this is the one photo the page is about
   while a rotation is live. 3:4 is WB's own card aspect. */
.ab-progress__photo {
  width: 84px;
  height: 112px;
  flex: none;
  object-fit: cover;
  border-radius: var(--ui-r-md);
  box-shadow: var(--ui-sh-sm);
}

.ab-progress__photo--empty {
  background: var(--ui-sunk);
}
</style>
