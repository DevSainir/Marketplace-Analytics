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
 * **The block is the table's column sums.** The backend builds both from the
 * same interval rows, so «Показов» here equals the «Показов» line below, to the
 * impression. That is the property that makes the panel worth trusting instead
 * of worth checking.
 *
 * One clock, not two. «Длительность» is the summed length of the intervals that
 * carry the counts. Wall-clock time since the start used to sit beside it and
 * was answering a question nobody had: the difference between the two is idle
 * time, and «Остановлен» says that outright, with a date on it.
 *
 * The status and the live photo moved here from a panel of their own above.
 * Both are one line, and a whole card for two lines read as a section rather
 * than as the caption it is.
 */
import { computed } from 'vue'

import { STATUS_LABELS } from '@/modules/abTests'
import MetricHint from '@/modules/abTests/components/MetricHint.vue'

const props = defineProps({
  /** The open test, as the detail endpoint returns it. */
  test: { type: Object, required: true },
  /** variant_id -> object URL for the stored original. */
  imageUrls: { type: Object, default: () => ({}) },
})

const summary = computed(() => props.test.summary ?? {})

const measuredMs = computed(() => Number(summary.value.measured_minutes ?? 0) * 60_000)

/** The status, shown only when it is not the one the ticking figures imply. */
const statusLabel = computed(() =>
  props.test.status === 'running' ? '' : STATUS_LABELS[props.test.status] || props.test.status,
)

/**
 * Was the test stopped because somebody edited the card?
 *
 * A pause with no reason on the screen is the reading «сломалось». This one has
 * a cause the seller can act on, and it is the only stop the rotation will not
 * undo by itself — so it is said in a sentence rather than left to the word
 * «На паузе».
 */
const photoConflict = computed(() => !!props.test.photo_conflict_at)

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

/** When it started, when it stopped, and how much of that was measured. */
const facts = computed(() => [
  { key: 'started', label: 'Запущен', value: moment(props.test.started_at) },
  {
    key: 'stopped',
    label: 'Остановлен',
    value: moment(props.test.stopped_at),
    hint: 'Когда ротация в последний раз перестала двигаться — пауза считается наравне с завершением. У идущего теста здесь «—».',
  },
  {
    key: 'measured',
    label: 'Длительность',
    value: duration(measuredMs.value),
    hint: `Сумма длительностей ${count(summary.value.windows)} засчитанных отрезков — время, за которое собраны эти числа. Пауза и часы без работающей рекламы в неё не входят: за них счётчики не читаются и никакому фото ничего не начисляется.`,
  },
])

/** «3 фото из 8 успели набрать показы» — how much of the test has run at all. */
const coverage = computed(() => {
  const measured = Number(summary.value.variants_measured ?? 0)
  const total = Number(summary.value.variants_total ?? 0)
  return { measured, total, rounds: Number(summary.value.rounds_completed ?? 0) }
})

const active = computed(() =>
  (props.test.variants ?? []).find(
    (variant) => variant.variant_id === props.test.active_variant_id,
  ),
)

/** «Главное» for the baseline, «Вариант N» for a candidate. */
const activeLabel = computed(() => {
  if (!active.value) return ''
  return active.value.is_original ? 'Главное' : `Вариант ${active.value.position}`
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
    <div class="flex flex-wrap items-baseline gap-x-sm gap-y-xs">
      <h2 class="text-h3 font-semibold text-primary">Итог по тесту</h2>
      <span
        v-if="statusLabel"
        class="text-tiny font-semibold"
        :class="test.status === 'paused' ? 'text-status-warning' : 'text-muted'"
        data-testid="summary-status"
      >
        {{ statusLabel }}
      </span>
    </div>

    <p
      v-if="photoConflict"
      class="mt-sm rounded-btn bg-status-warning/10 px-sm py-xs text-tiny text-primary"
      data-testid="summary-photo-conflict"
    >
      Ротация остановлена {{ moment(test.photo_conflict_at) }}: на карточке оказалось главное фото,
      которое тест не устанавливал — скорее всего, его поменяли вручную в кабинете WB. Трафик с
      чужого фото ни одному варианту не зачтён. Проверьте карточку и запустите тест заново.
    </p>

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
        <dd
          class="text-tiny font-semibold tabular-nums text-primary"
          :data-testid="`fact-${fact.key}`"
        >
          {{ fact.value }}
        </dd>
        <MetricHint v-if="fact.hint" :text="fact.hint" />
      </div>
    </dl>

    <p class="mt-sm text-tiny text-muted">
      Показы набрали {{ coverage.measured }} фото из {{ coverage.total }}; кругов пройдено
      {{ coverage.rounds }}.
    </p>

    <div v-if="active" class="mt-md flex items-center gap-md" data-testid="summary-live-photo">
      <img
        v-if="imageUrls[active.variant_id]"
        :src="imageUrls[active.variant_id]"
        :alt="activeLabel"
        class="ab-summary__photo"
      />
      <div v-else class="ab-summary__photo ab-summary__photo--empty"></div>
      <div class="min-w-0">
        <p class="text-base font-semibold text-primary">Сейчас на карточке</p>
        <p class="text-tiny font-semibold text-action">{{ activeLabel }}</p>
      </div>
    </div>
  </section>
</template>

<style scoped>
/* 3:4 is WB's own card aspect; small, because this is a caption under the
   figures rather than the subject of the block. */
.ab-summary__photo {
  width: 60px;
  height: 80px;
  flex: none;
  object-fit: cover;
  border-radius: var(--ui-r-md);
  box-shadow: var(--ui-sh-sm);
}

.ab-summary__photo--empty {
  background: var(--ui-sunk);
}
</style>
