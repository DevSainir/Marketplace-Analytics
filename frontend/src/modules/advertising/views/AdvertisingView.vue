<script setup>
/**
 * «Реклама» — /advertising.
 *
 * Top to bottom: the toolbar (period and the bonus switch, which governs the
 * whole page); «Куда ушли деньги» — the headline strip over one card per kind
 * of campaign; the daily chart with ДРР; the
 * per-article table.
 *
 * Internal-only while it is being built (route meta and the API both say so).
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
      title="Реклама"
      subtitle="Куда ушли деньги на рекламу и что они принесли за выбранный период"
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
          text="За этот период рекламы не было"
        />
        <div v-else class="flex flex-col gap-xl">
          <section>
            <h2 class="mb-md text-h3 font-semibold text-primary">Куда ушли деньги</h2>
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
                Ещё {{ formatMoney(store.bids.untyped, store.currency) }} не разнесено по видам: WB
                не отдал настройки этих кампаний.
              </p>
            </div>
          </section>

          <section v-if="store.data.days.length > 1">
            <h2 class="mb-md text-h3 font-semibold text-primary">Открутка по дням</h2>
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
