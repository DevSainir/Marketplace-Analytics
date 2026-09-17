<script setup>
/**
 * «Сводка» — /labs/summary.
 *
 * The whole кабинет in one window: what it earned, what it kept, and which
 * articles produced both. Every figure comes from one request, so the cards and
 * the charts can never be showing two different periods.
 *
 * Only the period costs a request. The price base, the cut, the sort order and
 * the folded tail are all answered from the payload — it carries both bases and
 * every article row — because each of those used to mean re-aggregating the
 * whole settlement window on the server.
 */
import { computed, onMounted } from 'vue'

import { CUTS, SORTS } from '@/modules/summary/categories'
import SummaryBusyBar from '@/modules/summary/components/SummaryBusyBar.vue'
import SummaryCategoryBars from '@/modules/summary/components/SummaryCategoryBars.vue'
import SummaryControls from '@/modules/summary/components/SummaryControls.vue'
import SummaryKpis from '@/modules/summary/components/SummaryKpis.vue'
import SummaryLineChart from '@/modules/summary/components/SummaryLineChart.vue'
import { orderSeries, revenueSeries, saleSeries } from '@/modules/summary/series'
import { useSummaryStore } from '@/modules/summary/store'

const store = useSummaryStore()

const labels = computed(() => store.days.map((day) => day.day))

const dayCharts = computed(() => [
  { title: 'Заказы и ДРР в день', series: orderSeries(store.days, { base: store.revenueBase }) },
  { title: 'Продажи и ДРР в день', series: saleSeries(store.days, { base: store.revenueBase }) },
])

const revenueLines = computed(() =>
  revenueSeries(store.days, { base: store.revenueBase, costed: !store.marginBlocked }),
)

const hasDays = computed(() => store.days.length > 0)

onMounted(() => store.init())
</script>

<template>
  <div class="app-container py-lg">
    <header class="mb-lg">
      <h1 class="text-h2 font-bold text-primary">Сводка</h1>
      <p class="mt-xs text-base text-muted">Сводные показатели по кабинету за выбранный период</p>
    </header>

    <SummaryControls
      :date-from="store.dateFrom"
      :date-to="store.dateTo"
      :span="store.span"
      :revenue-base="store.revenueBase"
      :is-all-history="store.isAllHistory"
      @period="store.setPeriod"
      @preset-days="store.setPresetDays"
      @preset-all="store.setPresetAll"
      @base="store.revenueBase = $event"
    />

    <SummaryBusyBar v-if="store.loading" class="mb-md" />

    <p v-if="store.error" class="text-base text-status-negative">{{ store.error }}</p>

    <template v-else-if="store.kpi">
      <!-- The previous window stays on screen while the next one loads, dimmed
           and inert: blanking it would make every preset click a full page
           rebuild, and the figures below are still the ones the header names
           until the response lands. -->
      <div :class="{ 'sum-stale': store.loading }">
        <SummaryKpis
          :kpi="store.kpi"
          :currency="store.currency"
          :revenue-base="store.revenueBase"
        />

        <section class="ui-sec">
          <h2 class="ui-sec__title">Выручка</h2>
          <div class="sum-card mt-md">
            <div class="sum-legend">
              <span v-for="line in revenueLines" :key="line.name" class="sum-legend__item">
                <span class="sum-legend__swatch" :style="{ background: line.color }"></span>
                {{ line.name }}
              </span>
            </div>
            <SummaryLineChart
              v-if="hasDays"
              :series="revenueLines"
              :labels="labels"
              :currency="store.currency"
            />
            <p v-else class="text-base text-muted">За период нет расчётов WB.</p>
          </div>
        </section>

        <section class="ui-sec grid gap-lg lg:grid-cols-2">
          <div v-for="chart in dayCharts" :key="chart.title">
            <h2 class="ui-sec__title">{{ chart.title }}</h2>
            <div class="sum-card mt-md">
              <div class="sum-legend">
                <span v-for="line in chart.series" :key="line.name" class="sum-legend__item">
                  <span class="sum-legend__swatch" :style="{ background: line.color }"></span>
                  {{ line.name }}
                </span>
              </div>
              <SummaryLineChart
                v-if="hasDays"
                :series="chart.series"
                :labels="labels"
                :height="196"
                plain
              />
            </div>
          </div>
        </section>

        <section class="ui-sec">
          <div class="flex flex-wrap items-center justify-between gap-md">
            <h2 class="ui-sec__title">Выручка по категории</h2>
            <div class="flex flex-wrap items-center gap-lg">
              <div class="flex items-center gap-xs">
                <button
                  v-for="option in SORTS"
                  :key="option.key"
                  type="button"
                  class="ui-chip"
                  :class="{ 'is-on': store.sort === option.key }"
                  @click="store.sort = option.key"
                >
                  {{ option.label }}
                </button>
              </div>
              <div class="flex items-center gap-xs">
                <button
                  v-for="option in CUTS"
                  :key="option.key"
                  type="button"
                  class="ui-chip"
                  :class="{ 'is-on': store.cut === option.key }"
                  @click="store.cut = option.key"
                >
                  {{ option.label }}
                </button>
              </div>
            </div>
          </div>
          <div class="sum-card mt-md">
            <SummaryCategoryBars
              :categories="store.categories"
              :currency="store.currency"
              :cut="store.cut"
            />
          </div>
        </section>
      </div>
    </template>
  </div>
</template>

<style scoped>
/* Dimmed and inert, never hidden — see the comment at the wrapper. */
.sum-stale {
  opacity: 0.45;
  pointer-events: none;
  transition: opacity 120ms ease-out;
}

/* The design system's card recipe, in tokens: elevated surface, 1px ring,
   layered shadow — never a border plus a big soft blur. */
.sum-card {
  padding: 16px 18px;
  border-radius: var(--ui-r-lg);
  background: var(--ui-surface);
  box-shadow: var(--ui-sh-sm);
}

.sum-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  margin-bottom: 10px;
  font-size: 0.75rem;
  color: var(--ui-muted);
}

.sum-legend__item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.sum-legend__swatch {
  width: 11px;
  height: 3px;
  border-radius: 2px;
}
</style>
