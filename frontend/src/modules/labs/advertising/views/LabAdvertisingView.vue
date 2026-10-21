<script setup>
/**
 * «Реклама» — /labs/advertising, the live page re-laid in the Bold Clarity kit.
 *
 * Copied one for one from `modules/advertising` on 2026-10-07, then re-laid the
 * same day to try the Bold Clarity design kit (not part of this repo) against the
 * page it would replace — same API, same figures, so the two can be opened side by
 * side on one workspace and period.
 *
 * What is the kit's and what is ours: colours, type and charts come from
 * `bold/visual.css` and `bold/charts.js` as the kit ships them; the layout is
 * this page's own, built by the kit's rules — the answer first and large, one
 * band per question, a sentence before any figure list, the table last.
 *
 * Top to bottom: the settings line (period and the bonus switch, which governs
 * the whole page); the answer (spend, what DRR means, three facts); «Куда ушли
 * деньги»; «Открутка по дням»; the per-article list and the table behind it.
 *
 * Internal-only while it is being built (route meta and the API both say so).
 */
import '@/modules/labs/advertising/bold/visual.css'
import '@/modules/labs/advertising/bold/layout.css'

import { computed, onMounted } from 'vue'

import BusyRegion from '@/core/components/BusyRegion.vue'
import DataState from '@/core/components/DataState.vue'
import PeriodSelector from '@/core/components/PeriodSelector.vue'
import AdsBonusSwitch from '@/modules/labs/advertising/components/AdsBonusSwitch.vue'
import AdsDailyChart from '@/modules/labs/advertising/components/AdsDailyChart.vue'
import AdsHero from '@/modules/labs/advertising/components/AdsHero.vue'
import AdsMoneySplit from '@/modules/labs/advertising/components/AdsMoneySplit.vue'
import { MAX_PERIOD_DAYS, useLabAdvertisingStore } from '@/modules/labs/advertising/store'
import LabAdvertisingSkuSection from '@/modules/labs/advertising/views/LabAdvertisingSkuSection.vue'

const store = useLabAdvertisingStore()

onMounted(() => store.init())

const settledTo = computed(() => store.data?.settled_to ?? null)
</script>

<template>
  <div class="bc">
    <div class="band band--top">
      <div class="app-container settings">
        <h1 class="t-display">Реклама</h1>
        <div class="controls">
          <PeriodSelector
            :from="store.dateFrom"
            :to="store.dateTo"
            :history-from="store.span?.date_from ?? ''"
            :max-days="MAX_PERIOD_DAYS"
            @range="store.setPeriod($event.from, $event.to)"
          />
          <AdsBonusSwitch
            :on="store.showBonus"
            :available="store.hasBonus"
            :locked="store.bonusLocked"
            @update:on="store.setShowBonus"
          />
        </div>
      </div>
    </div>

    <div v-if="!store.data" class="app-container">
      <DataState v-if="store.loading" kind="loading" />
      <DataState v-else-if="store.error" kind="error" :text="store.error" />
    </div>

    <template v-else>
      <div v-if="store.error" class="app-container">
        <DataState kind="error" layout="line" :text="store.error" />
      </div>
      <BusyRegion :busy="store.loading">
        <div v-if="!store.data.days.length" class="app-container">
          <DataState kind="empty" text="За этот период рекламы не было" />
        </div>
        <template v-else>
          <AdsHero
            :totals="store.totals"
            :currency="store.currency"
            :show-bonus="store.bonusVisible"
            :drr-comparable="store.drrComparable"
            :date-from="store.dateFrom"
            :date-to="store.dateTo"
          />
          <AdsMoneySplit
            :cards="store.bids.cards"
            :untyped="store.bids.untyped"
            :currency="store.currency"
            :show-bonus="store.bonusVisible"
          />
          <AdsDailyChart
            v-if="store.data.days.length > 1"
            :days="store.data.days"
            :currency="store.currency"
            :show-bonus="store.bonusVisible"
            :show-drr="store.drrComparable && Boolean(settledTo)"
          />
          <LabAdvertisingSkuSection />
        </template>
      </BusyRegion>
    </template>
  </div>
</template>
