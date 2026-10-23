<script setup>
/**
 * "Advertising" — /advertising.
 *
 * Top to bottom: the toolbar (period and the bonus switch, which governs the
 * whole page); "Where the money went" — the headline strip over one card per kind
 * of campaign; the daily chart with DRR; the
 * per-article table.
 */
import { computed, onMounted } from 'vue'

import PageHeader from '@/core/components/PageHeader.vue'
import BusyRegion from '@/core/components/BusyRegion.vue'
import DataState from '@/core/components/DataState.vue'
import PeriodSelector from '@/core/components/PeriodSelector.vue'
import { formatMoney } from '@/core/utils/format'
import AdsBidCards from '@/modules/advertising/components/AdsBidCards.vue'
import AdsBonusSwitch from '@/modules/advertising/components/AdsBonusSwitch.vue'
import AdsDailyChart from '@/modules/advertising/components/AdsDailyChart.vue'
import AdsKpis from '@/modules/advertising/components/AdsKpis.vue'
import { MAX_PERIOD_DAYS, useAdvertisingStore } from '@/modules/advertising/store'
import AdvertisingSkuSection from '@/modules/advertising/views/AdvertisingSkuSection.vue'
import { BackfillNotice } from '@/modules/profile'

const store = useAdvertisingStore()

onMounted(() => store.init())

const settledTo = computed(() => store.data?.settled_to ?? null)
</script>

<template>
  <div class="app-container py-lg">
    <PageHeader
      title="Advertising"
      subtitle="Where the ad money went and what it brought in over the period"
    />
    <BackfillNotice :lanes="['advertising', 'pnl']" />

    <div class="mb-lg flex flex-wrap items-center gap-md">
      <PeriodSelector
        :from="store.dateFrom"
        :to="store.dateTo"
        :history-from="store.span?.date_from ?? ''"
        :max-days="MAX_PERIOD_DAYS"
        @range="store.setPeriod($event.from, $event.to)"
      />
      <AdsBonusSwitch
        :on="store.showBonus"
        :locked="store.bonusLocked"
        @update:on="store.setShowBonus"
      />
    </div>

    <DataState v-if="!store.data && store.loading" kind="loading" />
    <DataState v-else-if="!store.data && store.error" kind="error" :text="store.error" />

    <template v-else-if="store.data">
      <DataState v-if="store.error" kind="error" layout="line" :text="store.error" class="mb-md" />
      <BusyRegion :busy="store.loading">
        <DataState
          v-if="!store.data.days.length"
          kind="empty"
          text="No advertising in this period"
        />
        <div v-else class="flex flex-col gap-xl">
          <section>
            <h2 class="mb-md text-h3 font-semibold text-primary">Where the money went</h2>
            <div class="flex flex-col gap-md">
              <AdsKpis
                :totals="store.totals"
                :currency="store.currency"
                :show-bonus="store.bonusVisible"
                :drr-comparable="store.drrComparable"
              />
              <AdsBidCards
                :cards="store.bids.cards"
                :currency="store.currency"
                :show-bonus="store.bonusVisible"
              />
              <p v-if="store.bids.untyped" class="text-tiny text-muted">
                Another {{ formatMoney(store.bids.untyped, store.currency) }} has no campaign type:
                WB didn't send these campaigns' settings.
              </p>
            </div>
          </section>

          <section v-if="store.data.days.length > 1">
            <h2 class="mb-md text-h3 font-semibold text-primary">Daily spend</h2>
            <AdsDailyChart
              :days="store.data.days"
              :currency="store.currency"
              :show-bonus="store.bonusVisible"
              :show-drr="store.drrComparable && Boolean(settledTo)"
            />
          </section>

          <AdvertisingSkuSection />
        </div>
      </BusyRegion>
    </template>
  </div>
</template>
