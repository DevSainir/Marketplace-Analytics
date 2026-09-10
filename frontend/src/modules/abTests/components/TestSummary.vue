<script setup>
/**
 * «Итог по тесту» — what the whole test has counted, above the comparison.
 *
 * The page had no answer to the first question anyone asks of it. The table
 * says photo 3 is ahead; it does not say whether that verdict rests on eight
 * hundred impressions or eighty thousand, how long it took to collect them, or
 * what the advertising spent meanwhile. Every one of those changes what the
 * comparison is worth, and all of them were derivable only by adding a row up
 * by hand.
 *
 * **The block is the table's column sums, and it says so.** The backend builds
 * both from the same interval rows, so «Показов» here equals the «Показов» line
 * below, to the impression. That is the property that makes the panel worth
 * trusting instead of worth checking, and it is why `Как это посчитано`
 * spells out the derivation rather than describing it — a summary a reader
 * cannot reconcile with the data under it is a second source of truth.
 *
 * Two clocks, deliberately both shown:
 *
 * * **Прошло** — wall clock since the first photo went up. Ticks here, locally,
 *   because for a live test it ends at «сейчас»; a duration serialised by the
 *   backend would be stale before it reached the screen.
 * * **Измерено** — the summed length of the intervals that carry the counts.
 *
 * Their difference is every stretch the test was not accruing: a hand pause, a
 * campaign that stopped serving. Showing only the first would present four
 * hours of data as fourteen hours' worth of confidence; showing only the second
 * hides that the test has been idle since lunch.
 */
import { computed, onUnmounted, ref } from 'vue'

import MetricHint from '@/modules/abTests/components/MetricHint.vue'

const props = defineProps({
  /** The open test, as the detail endpoint returns it. */
  test: { type: Object, required: true },
})

const summary = computed(() => props.test.summary ?? {})

const expanded = ref(false)

// The wall clock ticks under the reader; see the header comment.
const now = ref(Date.now())
const ticking = setInterval(() => (now.value = Date.now()), 1000)
onUnmounted(() => clearInterval(ticking))

/** Milliseconds from the first install to the finish, or to now. */
const elapsedMs = computed(() => {
  const started = Date.parse(props.test.started_at ?? '')
  if (Number.isNaN(started)) return null
  const finished = Date.parse(props.test.finished_at ?? '')
  return Math.max(0, (Number.isNaN(finished) ? now.value : finished) - started)
})

const measuredMs = computed(() => Number(summary.value.measured_minutes ?? 0) * 60_000)

/**
 * Time the test stood without accruing anything.
 *
 * Clamped at zero rather than trusted: the two clocks come from different
 * sources — one from the reader's browser, one from summed intervals — and a
 * few seconds of skew must not render as «-1 мин простоя».
 */
const idleMs = computed(() =>
  elapsedMs.value === null ? null : Math.max(0, elapsedMs.value - measuredMs.value),
)

/** The four figures the block leads with. */
const tiles = computed(() => [
  {
    key: 'views',
    label: 'Показов',
    value: count(summary.value.views),
    hint: 'Сумма показов всех фото за весь тест — ровно сумма строки «Показов» в таблице ниже. Это реклама: органические показы WB не отдаёт ни в одном API.',
  },
  {
    key: 'clicks',
    label: 'Кликов',
    value: count(summary.value.clicks),
    hint: 'Сколько раз из этих показов перешли в карточку. Тоже сумма одноимённой строки таблицы.',
  },
  {
    key: 'ctr',
    label: 'CTR теста',
    value: percent(summary.value.click_through),
    hint: 'Все клики теста, делённые на все его показы. Не среднее из CTR отдельных фото: у них разный трафик, и среднее приравняло бы фото со ста показами к фото с десятью тысячами.',
  },
  {
    key: 'spend',
    label: 'Расход рекламы',
    value: money(summary.value.spend),
    hint: 'Сколько реклама потратила на этот артикул за засчитанные отрезки. Это не цена теста: деньги тратит кампания, тест лишь меняет фото у трафика, за который вы платите в любом случае.',
  },
])

/** The facts under the tiles: when, how long, how much of it counted. */
const facts = computed(() => [
  { key: 'started', label: 'Запущен', value: moment(props.test.started_at) },
  {
    key: 'finished',
    label: props.test.finished_at ? 'Завершён' : 'Статус',
    value: props.test.finished_at ? moment(props.test.finished_at) : liveLabel.value,
  },
  { key: 'elapsed', label: 'Прошло', value: duration(elapsedMs.value) },
  {
    key: 'measured',
    label: 'Измерено',
    value: duration(measuredMs.value),
    hint: `Сумма длительностей ${count(summary.value.windows)} засчитанных отрезков. Меньше «Прошло» на ${duration(idleMs.value)} — столько тест простоял на паузе или без работающей рекламы, и это время никакому фото не зачтено.`,
  },
  { key: 'fresh', label: 'Данные по', value: moment(summary.value.last_window_at) },
])

const liveLabel = computed(() => (props.test.status === 'running' ? 'Идёт' : 'Не завершён'))

/** «3 фото из 8 успели набрать показы» — how much of the test has run at all. */
const coverage = computed(() => {
  const measured = Number(summary.value.variants_measured ?? 0)
  const total = Number(summary.value.variants_total ?? 0)
  return { measured, total, rounds: Number(summary.value.rounds_completed ?? 0) }
})

function count(value) {
  return Number(value ?? 0).toLocaleString('ru-RU')
}

function percent(value) {
  return value === null || value === undefined ? '—' : `${Number(value).toFixed(2)} %`
}

function money(value) {
  return `${Math.round(Number(value ?? 0)).toLocaleString('ru-RU')} ₽`
}

function moment(value) {
  const parsed = Date.parse(value ?? '')
  if (Number.isNaN(parsed)) return '—'
  return new Date(parsed).toLocaleString('ru-RU', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** `Хч Ym`, or minutes alone under an hour — a test may run for days. */
function duration(ms) {
  if (ms === null || ms === undefined) return '—'
  const minutes = Math.floor(ms / 60_000)
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
    aria-label="Итог по тесту"
    data-testid="test-summary"
  >
    <h2 class="text-h3 font-semibold text-primary">Итог по тесту</h2>

    <dl class="mt-md grid grid-cols-4 gap-md phone:grid-cols-2">
      <div v-for="tile in tiles" :key="tile.key">
        <dt class="flex items-center gap-xs text-tiny font-medium text-muted">
          <span>{{ tile.label }}</span>
          <MetricHint :text="tile.hint" />
        </dt>
        <dd
          class="mt-xs text-h2 font-bold tabular-nums text-primary"
          :data-testid="`summary-${tile.key}`"
        >
          {{ tile.value }}
        </dd>
      </div>
    </dl>

    <dl class="mt-lg flex flex-wrap gap-x-lg gap-y-sm border-t border-border-subtle pt-md">
      <div v-for="fact in facts" :key="fact.key" class="flex items-baseline gap-xs">
        <dt class="text-tiny text-muted">{{ fact.label }}</dt>
        <dd class="text-tiny font-semibold tabular-nums text-primary">{{ fact.value }}</dd>
        <MetricHint v-if="fact.hint" :text="fact.hint" />
      </div>
    </dl>

    <p class="mt-sm text-tiny text-muted">
      Показы набрали {{ coverage.measured }} фото из {{ coverage.total }}; кругов пройдено
      {{ coverage.rounds }}.
    </p>

    <button
      type="button"
      class="mt-sm rounded-btn text-tiny font-semibold text-action transition hover:underline"
      data-testid="summary-explain"
      @click="expanded = !expanded"
    >
      {{ expanded ? 'Свернуть' : 'Как это посчитано' }}
    </button>

    <div v-if="expanded" class="mt-sm space-y-sm text-tiny leading-relaxed text-muted">
      <p>
        Раз в 5 минут мы читаем накопительные счётчики рекламы WB по этому артикулу и записываем
        <strong class="text-primary">разницу</strong> с прошлым чтением на то фото, которое стояло
        на карточке весь этот отрезок. Смена фото происходит сразу после закрытия отрезка, поэтому
        ни один отрезок не делится между двумя вариантами.
      </p>
      <p>
        Все четыре числа наверху — сумма этих отрезков по всему тесту, из тех же строк, из которых
        строится таблица ниже. Сложите строку «Показов» по всем фото — получится ровно
        {{ count(summary.views) }}.
      </p>
      <p>
        CTR теста — {{ count(summary.clicks) }} ÷ {{ count(summary.views) }}. Проценты нигде не
        усредняются: сначала складываются числа, потом одно деление.
      </p>
      <p>
        «Измерено» — сумма длительностей {{ count(summary.windows) }} отрезков, а не время с
        запуска. Пауза и часы без работающей рекламы в неё не входят: за них счётчики не читаются и
        никакому фото ничего не начисляется.
      </p>
    </div>
  </section>
</template>
