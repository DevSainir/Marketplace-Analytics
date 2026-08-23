<script setup>
/**
 * «Графики» — the account-wide charts page.
 *
 * The monitoring page answers «how is this card doing»; this one answers «how
 * is the account doing», over the same days and the same metric names. It is a
 * page of the monitoring module rather than a module of its own: it reads the
 * same SKUs, the same window and the same chart machinery, and a second module
 * would have had to import all three across a boundary built to forbid exactly
 * that.
 *
 * The summing is the backend's (`/monitoring/charts`) — a conversion rate is
 * not additive, so «all SKUs» cannot be assembled by adding up what this page
 * already has.
 */
import { computed, onMounted, ref, watch } from 'vue'

import PeriodSelector from '@/core/components/PeriodSelector.vue'
import { isoDaysAgo } from '@/core/utils/dates'

import MetricsChart from '@/modules/monitoring/components/MetricsChart.vue'
import SkuMultiSelect from '@/modules/monitoring/components/SkuMultiSelect.vue'
import {
  AGGREGATE_DEFAULT_METRICS,
  AGGREGATE_METRIC_GROUPS,
} from '@/modules/monitoring/metricChart'
import { useMonitoringStore } from '@/modules/monitoring/store'

const store = useMonitoringStore()

// Same default window as the monitoring page, so switching between the two
// does not silently move the goalposts.
const dateFrom = ref(isoDaysAgo(30))
const dateTo = ref(isoDaysAgo(0))
/** Empty = every SKU in the workspace (see `SkuMultiSelect`). */
const selectedSkus = ref([])

function load() {
  store.fetchAggregate({
    date_from: dateFrom.value,
    date_to: dateTo.value,
    nmIds: selectedSkus.value,
  })
}

// The picker and the calendar both re-ask; the store aborts the request in
// flight, so dragging through a few SKUs does not race four responses.
watch([dateFrom, dateTo, selectedSkus], load, { deep: true })

onMounted(() => {
  store.fetchSkuList({ date_from: dateFrom.value, date_to: dateTo.value })
  load()
})

const scope = computed(() =>
  selectedSkus.value.length
    ? `Выбрано артикулов: ${selectedSkus.value.length}`
    : `Все артикулы с данными за период: ${store.aggregateSkuCount}`,
)
</script>

<template>
  <div class="app-container py-lg">
    <div class="w-full">
      <h1 class="text-h2 font-bold text-primary">Графики</h1>
      <p class="mt-xs max-w-3xl text-tiny font-medium text-muted">
        Сводные показатели по всем артикулам за выбранный период. Метрики суммируются по дням, а
        конверсии и ДРР считаются от этих сумм — не как среднее по артикулам.
      </p>

      <div class="mt-md flex flex-wrap items-end gap-md">
        <PeriodSelector v-model:from="dateFrom" v-model:to="dateTo" />
        <div class="min-w-64 flex-1 phone:w-full">
          <label class="mb-xs block text-tiny font-medium text-muted">Артикулы</label>
          <SkuMultiSelect
            v-model="selectedSkus"
            :items="store.skuList"
            :loading="store.skuListLoading"
          />
        </div>
      </div>

      <p class="mt-sm text-tiny text-muted">{{ scope }}</p>

      <p v-if="store.aggregateLoading" class="mt-lg text-center text-base text-muted">
        Считаем показатели…
      </p>

      <div
        v-else-if="store.aggregateError"
        class="mt-lg rounded-card bg-status-negative/10 p-md text-base text-status-negative"
      >
        <p class="font-semibold">Не удалось загрузить данные</p>
        <p class="mt-xs">{{ store.aggregateError }}</p>
      </div>

      <p
        v-else-if="!store.aggregateView.days.length"
        class="mt-20 text-center text-base text-muted phone:mt-xl"
      >
        За выбранный период нет данных ни по одному артикулу.
      </p>

      <MetricsChart
        v-else
        :view="store.aggregateView"
        :groups="AGGREGATE_METRIC_GROUPS"
        :default-metrics="AGGREGATE_DEFAULT_METRICS"
      />
    </div>
  </div>
</template>
