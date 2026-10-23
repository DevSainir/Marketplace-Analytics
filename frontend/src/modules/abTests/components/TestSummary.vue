<script setup>
/**
 * "Test summary" — what the whole test has counted, above the comparison.
 *
 * The page had no answer to the first question anyone asks of it. The table
 * says photo 3 is ahead; it does not say whether that verdict rests on eight
 * hundred impressions or eighty thousand, how long it took to collect them, or
 * what the advertising spent meanwhile. Every one of those changes what the
 * comparison is worth, and all of them were derivable only by adding a row up
 * by hand.
 *
 * **The block is the table's column sums.** The backend builds both from the
 * same interval rows, so "Impressions" here equals the "Impressions" line below, to the
 * impression. That is the property that makes the panel worth trusting instead
 * of worth checking.
 *
 * One clock, not two. "Duration" is the summed length of the intervals that
 * carry the counts. Wall-clock time since the start used to sit beside it and
 * was answering a question nobody had: the difference between the two is idle
 * time, and "Stopped" says that outright, with a date on it.
 *
 * The status and the live photo moved here from a panel of their own above.
 * Both are one line, and a whole card for two lines read as a section rather
 * than as the caption it is.
 *
 * **When more than one campaign paid for the traffic, each figure forks.** The
 * headline stays the whole test — a photo's impressions are its impressions whoever
 * bought them — and under it the same number is taken apart per campaign,
 * because "Unified" and "CPC" buy different traffic at different prices and a
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
import { formatMoscow } from '@/core/utils/moscow'

const props = defineProps({
  /** The open test, as the detail endpoint returns it. */
  test: { type: Object, required: true },
  /** variant_id -> object URL for the stored original. */
  imageUrls: { type: Object, default: () => ({}) },
  /** The workspace's settlement currency — what the spend is in; `''` prints it bare. */
  currency: { type: String, default: '' },
})

const summary = computed(() => props.test.summary ?? {})

/** The status, shown only when it is not the one the ticking figures imply. */
const statusLabel = computed(() => (props.test.status === 'running' ? '' : labelOf(props.test)))

/**
 * Was the test stopped because somebody edited the card?
 *
 * A pause with no reason on the screen reads as "broken". This one has
 * a cause the seller can act on, and it is the only stop the rotation will not
 * undo by itself — so it is said in a sentence rather than left to the word
 * "Paused".
 */
const photoConflict = computed(() => !!props.test.photo_conflict_at)

/**
 * Was the test stopped because nothing is advertising the card?
 *
 * The other stop a seller did not make. It undoes itself, which is exactly why
 * it has to be said: without the sentence a seller presses "Start", the
 * next pass finds the campaign still dry and pauses it again, and the page reads
 * as a test that "pauses on its own" — one workspace, 28 Sep 2026, twice in two hours.
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
    // "M-B…" four times over was telling the reader.
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
    label: 'Impressions',
    value: formatNumber(summary.value.views),
    branches: branches('views', formatNumber),
    hint: 'Impressions of every photo over the whole test.',
  },
  {
    key: 'clicks',
    label: 'Clicks',
    value: formatNumber(summary.value.clicks),
    branches: branches('clicks', formatNumber),
    hint: 'Clicks on every photo over the whole test.',
  },
  {
    key: 'ctr',
    label: 'Test CTR',
    value: formatPercent(summary.value.click_through),
    branches: branches('click_through', formatPercent),
    hint: 'All the test’s clicks divided by all its impressions.',
  },
  {
    key: 'spend',
    label: 'Ad spend',
    value: money(summary.value.spend),
    branches: branches('spend', money),
    hint: 'What advertising spent on this SKU while the test ran.',
  },
])

function money(value) {
  return formatMoney(value, props.currency)
}

/** "14 Oct, 10:47 MSK". */
function moment(value) {
  return formatMoscow(value, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}
</script>

<template>
  <section
    class="mb-lg rounded-card border border-border-subtle bg-surface p-lg shadow-card phone:p-md"
    aria-label="Test summary"
    data-testid="test-summary"
  >
    <div class="flex flex-wrap items-baseline gap-x-sm gap-y-xs">
      <h2 class="text-h3 font-semibold text-primary">Test summary</h2>
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
      Rotation stopped {{ moment(test.photo_conflict_at) }}: the card has a main photo the test did
      not install — most likely changed by hand in the WB seller portal. Its traffic counts for no
      variant. Check the card and start the test again.
    </p>

    <p
      v-if="pausedByAds"
      class="mt-sm rounded-btn bg-status-warning/10 px-sm py-xs text-tiny text-primary"
      data-testid="summary-paused-by-ads"
    >
      Rotation stopped {{ moment(test.stopped_at) }}: no ads are running on this SKU — the campaigns
      are paused, out of budget or missing. Without ads there are no impressions and nothing to
      compare, whatever the mode. The test resumes on its own within 5 minutes of the ads running
      again: start a campaign for this SKU, top up its budget or turn it on in the WB seller portal.
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
