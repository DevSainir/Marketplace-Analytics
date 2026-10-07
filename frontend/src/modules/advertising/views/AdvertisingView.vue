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

import PeriodSelector from '@/core/components/PeriodSelector.vue'
import { formatMoney } from '@/core/utils/format'
import AdsBidCards from '@/modules/advertising/components/AdsBidCards.vue'
import AdsBonusSwitch from '@/modules/advertising/components/AdsBonusSwitch.vue'
import AdsDailyChart from '@/modules/advertising/components/AdsDailyChart.vue'
import AdsKpis from '@/modules/advertising/components/AdsKpis.vue'
import { MAX_PERIOD_DAYS, useAdvertisingStore } from '@/modules/advertising/store'
import AdvertisingSkuSection from '@/modules/advertising/views/AdvertisingSkuSection.vue'

const store = useAdvertisingStore()

onMounted(() => store.init())

const settledTo = computed(() => store.data?.settled_to ?? null)
</script>

<template>
  <div class="app-container py-lg">
    <header class="mb-lg">
      <h1 class="text-h2 font-bold text-primary">Реклама</h1>
    </header>

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
        :available="store.hasBonus"
        :locked="store.bonusLocked"
        @update:on="store.setShowBonus"
      />
    </div>

    <div v-if="store.loading && !store.data" class="py-xl text-center text-base text-muted">
      Загружаю данные…
    </div>
    <div v-else-if="store.error" class="py-xl text-center text-base text-status-negative">
      {{ store.error }}
    </div>
    <div
      v-else-if="store.data && !store.data.days.length"
      class="py-xl text-center text-base text-muted"
    >
      За этот период рекламы не было
    </div>

    <div
      v-else-if="store.data"
      class="flex flex-col gap-xl"
      :class="{ 'opacity-60 transition-opacity': store.loading }"
    >
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
            Ещё {{ formatMoney(store.bids.untyped, store.currency) }} не разнесено по видам: WB не
            отдал настройки этих кампаний.
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
  </div>
</template>
