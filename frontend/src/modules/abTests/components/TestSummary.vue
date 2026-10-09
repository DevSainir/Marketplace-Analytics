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
 *
 * **When more than one campaign paid for the traffic, each figure forks.** The
 * headline stays the whole test — a photo's показы are its показы whoever
 * bought them — and under it the same number is taken apart per campaign,
 * because «Единая» and «CPC» buy different traffic at different prices and a
 * campaign that starts or stops mid-test moves the total in a way that reads
 * like a photo winning. With one campaign there is nothing to take apart and
 * the block renders exactly as it did before.
 */
import { computed } from 'vue'

import { formatMoney, formatNumber, formatPercent } from '@/core/utils/format'
import { statusLabel as labelOf, statusTone } from '@/modules/abTests'
import { campaignKindLabel } from '@/modules/abTests/campaignKinds'
import SummaryFacts from '@/modules/abTests/components/SummaryFacts.vue'
import SummaryMetricTile from '@/modules/abTests/components/SummaryMetricTile.vue'

const props = defineProps({
  /** The open test, as the detail endpoint returns it. */
  test: { type: Object, required: true },
  /** variant_id -> object URL for the stored original. */
  imageUrls: { type: Object, default: () => ({}) },
  /** The кабинет's settlement currency — what the spend is in; `''` prints it bare. */
  currency: { type: String, default: '' },
})

const summary = computed(() => props.test.summary ?? {})

/** The status, shown only when it is not the one the ticking figures imply. */
const statusLabel = computed(() => (props.test.status === 'running' ? '' : labelOf(props.test)))

/**
 * Was the test stopped because somebody edited the card?
 *
 * A pause with no reason on the screen is the reading «сломалось». This one has
 * a cause the seller can act on, and it is the only stop the rotation will not
 * undo by itself — so it is said in a sentence rather than left to the word
 * «На паузе».
 */
const photoConflict = computed(() => !!props.test.photo_conflict_at)

/**
 * Was the test stopped because nothing is advertising the card?
 *
 * The other stop a seller did not make. It undoes itself, which is exactly why
 * it has to be said: without the sentence a seller presses «Запустить», the
 * next pass finds the campaign still dry and pauses it again, and the page reads
 * as a test that «сам уходит в паузу» — NEVA, 28.09.2026, twice in two hours.
 */
const pausedByAds = computed(() => props.test.status === 'paused' && !!props.test.paused_by_ads)

/** The campaigns that actually brought this test traffic, in the page's order. */
const campaigns = computed(() => props.test.campaigns ?? [])

/** Is there anything to take apart? One campaign is the ordinary case. */
const split = computed(() => campaigns.value.length > 1)

/**
 * The per-campaign row under one figure.
 *
 * @param {string} key The campaign field to read.
 * @param {(value: unknown) => string} format How the trunk formats the same figure.
 * @returns {Array<{id: number, name: string, title: string, value: string}>} One branch per
 *   campaign, empty when only one paid.
 */
function branches(key, format) {
  if (!split.value) return []
  return campaigns.value.map((campaign) => ({
    id: campaign.campaign_id,
    // The KIND, not the campaign's own name: see `campaignKinds.js` for what
    // «M-B…» four times over was telling the reader.
    name: campaignKindLabel(campaign),
    // The seller's own name is a hover away, which is also what tells two
    // campaigns of the same kind apart.
    title: campaign.name,
    value: format(campaign[key]),
  }))
}

/** The four figures the block leads with. */
const tiles = computed(() => [
  {
    key: 'views',
    label: 'Показов',
    value: formatNumber(summary.value.views),
    branches: branches('views', formatNumber),
    hint: 'Сумма показов всех фото за весь тест.',
  },
  {
    key: 'clicks',
    label: 'Кликов',
    value: formatNumber(summary.value.clicks),
    branches: branches('clicks', formatNumber),
    hint: 'Сумма переходов по всем фото за весь тест.',
  },
  {
    key: 'ctr',
    label: 'CTR теста',
    value: formatPercent(summary.value.click_through),
    branches: branches('click_through', formatPercent),
    hint: 'Все клики теста, делённые на все его показы.',
  },
  {
    key: 'spend',
    label: 'Расход на рекламу',
    value: money(summary.value.spend),
    branches: branches('spend', money),
    hint: 'Сколько реклама потратила на этот артикул за период проведения теста.',
  },
])

function money(value) {
  return formatMoney(value, props.currency)
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
</script>

<template>
  <section
    class="mb-lg rounded-card border border-border-subtle bg-surface p-lg shadow-card phone:p-md"
    aria-label="Итог по тесту"
    data-testid="test-summary"
  >
    <div class="flex flex-wrap items-baseline gap-x-sm gap-y-xs">
      <h2 class="text-h3 font-semibold text-primary">Итог по тесту</h2>
      <span
        v-if="statusLabel"
        class="ui-badge"
        :class="statusTone(test)"
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

    <p
      v-if="pausedByAds"
      class="mt-sm rounded-btn bg-status-warning/10 px-sm py-xs text-tiny text-primary"
      data-testid="summary-paused-by-ads"
    >
      Ротация остановлена {{ moment(test.stopped_at) }}: на артикуле не идёт реклама — кампании на
      паузе, у них закончился бюджет или кампании нет вовсе. Без рекламы нет показов, и сравнивать
      фото не на чем, в каком бы режиме ни шёл тест. Тест продолжится сам в течение 5 минут после
      того, как реклама пойдёт: запустите кампанию на этот артикул, пополните бюджет или включите её
      в кабинете WB.
    </p>

    <dl
      class="mt-md grid grid-cols-4 gap-lg phone:grid-cols-2"
      :class="split ? 'px-lg phone:px-0' : ''"
    >
      <SummaryMetricTile
        v-for="tile in tiles"
        :key="tile.key"
        :label="tile.label"
        :value="tile.value"
        :hint="tile.hint"
        :branches="tile.branches"
        :testid="`summary-${tile.key}`"
      />
    </dl>

    <SummaryFacts :test="test" :summary="summary" :image-urls="imageUrls" />
  </section>
</template>
