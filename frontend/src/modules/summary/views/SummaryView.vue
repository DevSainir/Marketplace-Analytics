<script setup>
/**
 * «Сводка» — /labs/summary.
 *
 * The whole кабинет in one window: what it earned, what it kept, and which
 * articles produced both. Every figure comes from one request, so the cards and
 * the charts can never be showing two different periods.
 *
 * Structure follows the finance one-pager this was modelled on — cards, then
 * «Выручка», then orders and advertising side by side, then «Выручка по
 * категории» — rendered in the app's own design system rather than that page's
 * second set of tokens.
 */
import { computed, onMounted } from 'vue'

import PeriodSelector from '@/core/components/PeriodSelector.vue'
import SummaryCategoryBars from '@/modules/summary/components/SummaryCategoryBars.vue'
import SummaryKpis from '@/modules/summary/components/SummaryKpis.vue'
import SummaryLineChart from '@/modules/summary/components/SummaryLineChart.vue'
import { useSummaryStore } from '@/modules/summary/store'

const store = useSummaryStore()

const BASES = [
  { key: 'paid', label: 'Цена реализации' },
  { key: 'seller', label: 'Цена карточки' },
]

const CUTS = [
  { key: 'sku', label: 'Артикулы' },
  { key: 'subject', label: 'Предметы' },
  { key: 'brand', label: 'Бренды' },
]

const labels = computed(() => store.days.map((day) => day.day))

const revenueSeries = computed(() => {
  const series = [
    {
      name: 'Выручка',
      color: 'var(--ui-action)',
      values: store.days.map((day) => Number(day.revenue)),
    },
  ]
  // The margin line is omitted entirely rather than drawn flat when the window
  // has an uncosted SKU: a zero line would be a claim, and this page does not
  // have the figure to make it.
  if (!store.marginBlocked) {
    series.push({
      name: 'Маржа',
      color: 'var(--ui-pos)',
      values: store.days.map((day) => (day.margin === null ? null : Number(day.margin))),
    })
  }
  return series
})

const orderSeries = computed(() => [
  {
    name: 'Заказы',
    color: 'var(--ui-action)',
    values: store.days.map((day) => (day.orders === null ? null : Number(day.orders))),
  },
])

const adSeries = computed(() => [
  {
    name: 'Реклама',
    color: 'var(--ui-warn)',
    values: store.days.map((day) => (day.ad_spend === null ? null : Number(day.ad_spend))),
  },
])

const hasDays = computed(() => store.days.length > 0)

onMounted(() => store.load())
</script>

<template>
  <div class="app-container py-lg">
    <header class="mb-lg">
      <h1 class="text-h2 font-bold text-primary">Сводка</h1>
      <p class="mt-xs text-base text-muted">Сводные показатели по кабинету за выбранный период</p>
    </header>

    <div class="mb-lg flex flex-wrap items-center gap-md">
      <PeriodSelector
        :from="store.dateFrom"
        :to="store.dateTo"
        @update:from="store.setPeriod($event, store.dateTo)"
        @update:to="store.setPeriod(store.dateFrom, $event)"
      />

      <div class="flex items-center gap-xs">
        <button
          v-for="base in BASES"
          :key="base.key"
          type="button"
          class="ui-chip"
          :class="{ 'is-on': store.revenueBase === base.key }"
          @click="store.setRevenueBase(base.key)"
        >
          {{ base.label }}
        </button>
      </div>
    </div>

    <p v-if="store.error" class="text-base text-status-negative">{{ store.error }}</p>

    <p v-else-if="store.loading && !store.kpi" class="text-base text-muted">Загружаю…</p>

    <template v-else-if="store.kpi">
      <SummaryKpis :kpi="store.kpi" :currency="store.currency" :revenue-base="store.revenueBase" />

      <section class="ui-sec">
        <h2 class="ui-sec__title">Выручка</h2>
        <div class="sum-card mt-md">
          <SummaryLineChart
            v-if="hasDays"
            :series="revenueSeries"
            :labels="labels"
            :currency="store.currency"
          />
          <p v-else class="text-base text-muted">За период нет расчётов WB.</p>
        </div>
      </section>

      <section class="ui-sec grid gap-lg lg:grid-cols-2">
        <div>
          <h2 class="ui-sec__title">Заказы</h2>
          <div class="sum-card mt-md">
            <SummaryLineChart
              v-if="hasDays"
              :series="orderSeries"
              :labels="labels"
              :height="196"
              plain
            />
          </div>
        </div>
        <div>
          <h2 class="ui-sec__title">Реклама</h2>
          <div class="sum-card mt-md">
            <SummaryLineChart
              v-if="hasDays"
              :series="adSeries"
              :labels="labels"
              :height="196"
              :currency="store.currency"
            />
          </div>
        </div>
      </section>

      <section class="ui-sec">
        <div class="flex flex-wrap items-center justify-between gap-md">
          <h2 class="ui-sec__title">Выручка по категории</h2>
          <div class="flex items-center gap-xs">
            <button
              v-for="cut in CUTS"
              :key="cut.key"
              type="button"
              class="ui-chip"
              :class="{ 'is-on': store.grouping === cut.key }"
              @click="store.setGrouping(cut.key)"
            >
              {{ cut.label }}
            </button>
          </div>
        </div>
        <div class="sum-card mt-md">
          <SummaryCategoryBars :categories="store.categories" :currency="store.currency" />
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
/* The design system's card recipe, in tokens: elevated surface, 1px ring,
   layered shadow — never a border plus a big soft blur. */
.sum-card {
  padding: 16px 18px;
  border-radius: var(--ui-r-lg);
  background: var(--ui-surface);
  box-shadow: var(--ui-sh-sm);
}
</style>
