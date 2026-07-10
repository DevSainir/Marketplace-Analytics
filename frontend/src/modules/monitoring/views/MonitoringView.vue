<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { isoDaysAgo } from '@/core/utils/dates'

import MetricsTable from '@/modules/monitoring/components/MetricsTable.vue'
import PeriodSelector from '@/modules/monitoring/components/PeriodSelector.vue'
import SkuSearchSelect from '@/modules/monitoring/components/SkuSearchSelect.vue'
import { buildMetricsMatrix } from '@/modules/monitoring/metricsMatrix'
import { useMonitoringStore } from '@/modules/monitoring/store'

const store = useMonitoringStore()
const route = useRoute()
const router = useRouter()

// Default inclusive window: the last 30 full days, current day excluded.
const DEFAULT_FROM = isoDaysAgo(30)
const DEFAULT_TO = isoDaysAgo(1)

/** Pick the search-relevant params out of a route query (arrays/absent → defaults). */
function readSearchQuery(query) {
  const pick = (key) => (typeof query[key] === 'string' ? query[key] : '')
  return {
    sku: pick('sku'),
    date_from: pick('date_from') || DEFAULT_FROM,
    date_to: pick('date_to') || DEFAULT_TO,
  }
}

// Draft period: edited freely, takes effect on «Применить» or on picking a SKU.
const initial = readSearchQuery(route.query)
const dateFrom = ref(initial.date_from)
const dateTo = ref(initial.date_to)

// The URL is the single source of truth (deep-linkable, survives refresh and
// back/forward): handlers only push a new query, this watcher does ALL
// fetching — the SKU list follows the window, the detail follows sku + window.
watch(
  () => route.query,
  (query, oldQuery) => {
    if (route.name !== 'monitoring') return // navigating away, not a new search
    const search = readSearchQuery(query)
    const old = oldQuery ? readSearchQuery(oldQuery) : null

    // Back/forward must also rewind the period selector.
    dateFrom.value = search.date_from
    dateTo.value = search.date_to

    if (!old || old.date_from !== search.date_from || old.date_to !== search.date_to) {
      store.fetchSkuList({ date_from: search.date_from, date_to: search.date_to })
    }

    if (!search.sku) {
      store.reset()
      return
    }
    if (old && JSON.stringify(search) === JSON.stringify(old)) return
    store.fetchProductData(search.sku, { date_from: search.date_from, date_to: search.date_to })
  },
  { immediate: true },
)

/** Dropdown pick: analyze this SKU over the drafted window. */
function handleSelect(item) {
  pushSearch(String(item.nm_id))
}

/**
 * «Применить»: apply the drafted period. A raw nm ID in the input is treated
 * as a direct pick; otherwise the currently analyzed SKU (if any) is kept.
 */
function handleApply(query) {
  const sku = /^\d+$/.test(query) ? query : readSearchQuery(route.query).sku
  pushSearch(sku)
}

// `push` (not `replace`) keeps every search reachable via the Back button.
function pushSearch(sku) {
  router.push({
    query: { ...(sku && { sku }), date_from: dateFrom.value, date_to: dateTo.value },
  })
}

const product = computed(() => store.currentProduct)

// Vendor code (артикул продавца) once the backend serves it; nm ID meanwhile.
const skuLabel = computed(() => product.value?.vendor_code ?? `SKU ${product.value?.nm_id ?? ''}`)

const windowLabel = computed(() => {
  const window = product.value?.window
  return window ? `${window.start} → ${window.end}` : ''
})

// Metric rows × day columns for the daily table (workbook replica).
const metricsMatrix = computed(() => buildMetricsMatrix(product.value))

/** «Обновить»: re-fetch the current search with the same window. */
function refresh() {
  const search = readSearchQuery(route.query)
  if (!search.sku) return
  store.fetchProductData(search.sku, {
    date_from: search.date_from,
    date_to: search.date_to,
  })
}

</script>

<template>
  <div class="mx-auto w-full max-w-7xl px-md py-lg sm:px-lg">
    <div class="w-full">
      <h1 class="sr-only">Мониторинг SKU</h1>

      <!-- Period selector, slightly above the search bar -->
      <PeriodSelector v-model:from="dateFrom" v-model:to="dateTo" class="mb-sm" />

      <!-- Search bar: apply on the left, dropdown with all SKUs below -->
      <SkuSearchSelect
        :items="store.skuList"
        :loading="store.skuListLoading"
        :selected-id="product?.nm_id ?? null"
        @select="handleSelect"
        @apply="handleApply"
      />

      <p v-if="store.skuListError" class="mt-sm text-tiny text-status-negative">
        Не удалось загрузить список SKU: {{ store.skuListError }}
      </p>

      <!-- Ambiguous vendor-code deep link: let the user pick the exact SKU -->
      <section
        v-if="store.lookupMatches.length"
        class="mt-lg rounded-card bg-surface/75 p-md shadow-card backdrop-blur-md"
      >
        <p class="text-base font-medium text-primary">
          Найдено артикулов: {{ store.lookupMatches.length }} — выберите нужный:
        </p>
        <div class="mt-sm flex flex-wrap gap-sm">
          <button
            v-for="match in store.lookupMatches"
            :key="match.nm_id"
            type="button"
            class="inline-flex max-w-full items-center gap-sm rounded-btn border border-border-subtle bg-surface px-sm py-xs text-base shadow-soft transition hover:border-action hover:bg-action/10"
            @click="handleSelect(match)"
          >
            <span class="font-semibold text-primary">{{ match.vendor_code }}</span>
            <span class="truncate text-tiny text-muted">{{ match.title }}</span>
          </button>
        </div>
      </section>

      <!-- Detail states -->
      <p v-if="store.loading" class="mt-lg text-center text-base text-muted">
        Загружаем статистику {{ skuLabel }}…
      </p>

      <div
        v-else-if="store.error"
        class="mt-lg rounded-card bg-status-negative/10 p-md text-base text-status-negative"
      >
        <p class="font-semibold">Не удалось загрузить данные</p>
        <p class="mt-xs">{{ store.error }}</p>
      </div>

      <p v-else-if="store.notFound" class="mt-lg text-center text-base text-muted">
        По артикулу «{{ store.notFound }}» ничего не найдено.
      </p>

      <!-- Product identity + daily metrics table after a SKU is submitted -->
      <template v-else-if="product">
        <div class="mt-lg flex flex-wrap items-baseline gap-x-sm gap-y-xs">
          <h2 class="text-h2 font-bold text-primary">{{ product.title ?? skuLabel }}</h2>
          <span v-if="product.vendor_code" class="text-base font-semibold text-status-positive">
            {{ product.vendor_code }}
          </span>
          <span class="text-tiny text-muted">SKU {{ product.nm_id }}</span>
          <span class="ml-auto text-base font-medium text-muted">{{ windowLabel }}</span>
        </div>

        <section class="mt-lg" aria-label="Ежедневные метрики">
          <h2 class="text-h3 font-semibold text-primary">Метрики по дням</h2>

          <MetricsTable class="mt-sm" :days="metricsMatrix.days" :rows="metricsMatrix.rows" />

          <div class="mt-sm flex justify-end gap-sm">
            <button
              type="button"
              disabled
              title="Скоро: сохранение ручных корректировок"
              class="inline-flex h-9 items-center justify-center rounded-btn bg-surface px-lg text-base font-medium text-muted shadow-soft disabled:cursor-not-allowed"
            >
              Сохранить
            </button>
            <button
              type="button"
              :disabled="store.loading"
              class="inline-flex h-9 items-center justify-center rounded-btn bg-action px-lg text-base font-semibold text-white shadow-soft transition hover:bg-action-hover disabled:cursor-not-allowed disabled:opacity-60"
              @click="refresh"
            >
              Обновить
            </button>
          </div>
        </section>
      </template>

      <!-- Initial state: an inviting hint until the first SKU is submitted -->
      <div v-else-if="!store.lookupMatches.length" class="mt-20 text-center">
        <p class="text-h2 font-semibold text-primary">Введите артикул товара</p>
        <p class="mx-auto mt-sm max-w-xl text-base text-muted">
          Начните вводить артикул продавца, nm ID или название — либо просто кликните по строке
          поиска и выберите SKU из списка. После этого здесь появится короткая сводка по заказам,
          рекламе и остаткам.
        </p>
      </div>
    </div>
  </div>
</template>
