<script setup>
/**
 * «Реклама» — /advertising.
 *
 * Top to bottom: the toolbar (period and the bonus switch, which governs the
 * whole page); «Куда ушли деньги» — one block of three full-width rows: the
 * headline cards, the zone tree, the zone pies; the daily chart with ДРР; the
 * per-article table.
 *
 * Internal-only while it is being built (route meta and the API both say so).
 */
import { computed, onMounted } from 'vue'

import PeriodSelector from '@/core/components/PeriodSelector.vue'
import { dateRu } from '@/modules/advertising/adsFormat'
import AdsBonusSwitch from '@/modules/advertising/components/AdsBonusSwitch.vue'
import AdsDailyChart from '@/modules/advertising/components/AdsDailyChart.vue'
import AdsKpis from '@/modules/advertising/components/AdsKpis.vue'
import AdsZonePies from '@/modules/advertising/components/AdsZonePies.vue'
import AdsZoneTable from '@/modules/advertising/components/AdsZoneTable.vue'
import { useAdvertisingStore } from '@/modules/advertising/store'
import AdvertisingSkuSection from '@/modules/advertising/views/AdvertisingSkuSection.vue'

const store = useAdvertisingStore()

onMounted(() => store.init())

const period = computed(() => `${dateRu(store.dateFrom)} — ${dateRu(store.dateTo)}`)
const settledTo = computed(() => store.data?.settled_to ?? null)
</script>

<template>
  <div class="app-container py-lg">
    <header class="mb-lg">
      <h1 class="text-h2 font-bold text-primary">Реклама</h1>
      <p class="mt-xs text-tiny text-muted">
        Куда ушли деньги на рекламу, что они принесли и сколько из них оплатил WB
      </p>
    </header>

    <div class="mb-lg flex flex-wrap items-center gap-md">
      <PeriodSelector
        :from="store.dateFrom"
        :to="store.dateTo"
        :preset-end="store.span?.date_to ?? ''"
        @range="store.setPeriod($event.from, $event.to)"
      />
      <AdsBonusSwitch
        :on="store.showBonus"
        :available="store.hasBonus"
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
        <h2 class="text-h3 font-semibold text-primary">Куда ушли деньги</h2>
        <p class="mb-md mt-xs max-w-prose text-tiny text-muted">
          Расход по статистике кампаний, разложенный по типу оплаты, ставке и зоне показа. Поиск
          измерен по поисковым кластерам, остаток кампании — полки или каталог.
        </p>
        <div class="flex flex-col gap-md">
          <AdsKpis
            :totals="store.totals"
            :currency="store.currency"
            :show-bonus="store.bonusVisible"
            :period="period"
            :settled-to="settledTo"
            :drr-comparable="store.drrComparable"
          />
          <AdsZoneTable
            :rows="store.zones"
            :currency="store.currency"
            :show-bonus="store.bonusVisible"
          />
          <AdsZonePies v-if="store.pies.length" :pies="store.pies" :currency="store.currency" />
        </div>
      </section>

      <section v-if="store.data.days.length > 1">
        <h2 class="text-h3 font-semibold text-primary">Открутка по дням</h2>
        <p class="mb-md mt-xs max-w-prose text-tiny text-muted">
          День показа рекламы. ДРР от продаж — реклама дня к продажам дня по отчёту
          реализации<template v-if="settledTo">, рассчитан по {{ dateRu(settledTo) }}</template
          >.
        </p>
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
