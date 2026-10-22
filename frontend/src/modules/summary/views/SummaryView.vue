<script setup>
/**
 * «Сводка» — /summary.
 *
 * The whole workspace in one window: what it earned, what it kept, and which
 * articles produced both. Every figure comes from one request, so the cards and
 * the charts can never be showing two different periods.
 *
 * Only the period costs a request. The price base, the cut, the sort order and
 * the folded tail are all answered from the payload — it carries both bases and
 * every article row — because each of those used to mean re-aggregating the
 * whole settlement window on the server.
 */
import { computed, onMounted } from 'vue'

import PageHeader from '@/core/components/PageHeader.vue'
import BusyRegion from '@/core/components/BusyRegion.vue'
import DataState from '@/core/components/DataState.vue'
import GroupingChips from '@/core/components/GroupingChips.vue'
import { SORTS } from '@/modules/summary/categories'
import SummaryCategoryBars from '@/modules/summary/components/SummaryCategoryBars.vue'
import SummaryControls from '@/modules/summary/components/SummaryControls.vue'
import SummaryKpis from '@/modules/summary/components/SummaryKpis.vue'
import SummaryLineChart from '@/modules/summary/components/SummaryLineChart.vue'
import { orderSeries, revenueSeries, saleSeries } from '@/modules/summary/series'
import { useSummaryStore } from '@/modules/summary/store'
import { BackfillNotice } from '@/modules/profile'

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
    <PageHeader title="Сводка" subtitle="Сводные показатели по кабинету за выбранный период" />
    <BackfillNotice :lanes="['pnl']" />

    <SummaryControls
      :date-from="store.dateFrom"
      :date-to="store.dateTo"
      :span="store.span"
      :revenue-base="store.revenueBase"
      @period="store.setPeriod"
      @base="store.revenueBase = $event"
    />

    <DataState v-if="!store.kpi && store.loading" kind="loading" />
    <DataState v-else-if="!store.kpi && store.error" kind="error" :text="store.error" />

    <template v-else-if="store.kpi">
      <DataState v-if="store.error" kind="error" layout="line" :text="store.error" class="mb-md" />
      <BusyRegion :busy="store.loading">
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
            <DataState v-else kind="empty" layout="bare" />
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
              <DataState v-else kind="empty" layout="bare" />
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
              <GroupingChips v-model="store.cut" :groups="store.groupsReadable" />
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
      </BusyRegion>
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
