<script setup>
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { formatCurrency, formatNumber, formatPercent } from '@/core/utils/format'

import CampaignAttributionTable from '@/modules/monitoring/components/CampaignAttributionTable.vue'
import MetricCard from '@/modules/monitoring/components/MetricCard.vue'
import SkuSearchBar from '@/modules/monitoring/components/SkuSearchBar.vue'
import StockBreakdownTable from '@/modules/monitoring/components/StockBreakdownTable.vue'
import { useMonitoringStore } from '@/modules/monitoring/store'

const store = useMonitoringStore()
const route = useRoute()
const router = useRouter()

// The search is deep-linkable: /monitoring?sku=…&date_from=…&date_to=…
// survives refresh, back/forward, and can be shared between managers.
const initialSearch = {
  sku: typeof route.query.sku === 'string' ? route.query.sku : '',
  date_from: typeof route.query.date_from === 'string' ? route.query.date_from : '',
  date_to: typeof route.query.date_to === 'string' ? route.query.date_to : '',
}

onMounted(() => {
  if (initialSearch.sku) {
    store.fetchProductData(initialSearch.sku, {
      ...(initialSearch.date_from && { date_from: initialSearch.date_from }),
      ...(initialSearch.date_to && { date_to: initialSearch.date_to }),
    })
  }
})

const product = computed(() => store.currentProduct)

// Vendor code (артикул продавца) once the backend serves it; nm ID meanwhile.
const skuLabel = computed(() => product.value?.vendor_code ?? `SKU ${product.value?.nm_id ?? ''}`)

const windowLabel = computed(() => {
  const window = product.value?.window
  return window ? `${window.start} → ${window.end}` : ''
})

const metricCards = computed(() => [
  {
    label: 'Корзины',
    value: formatNumber(store.totalCarts),
    hint: 'Добавления в корзину за период',
    tone: 'neutral',
  },
  {
    label: 'Клики по рекламе',
    value: formatNumber(store.totalAdClicks),
    hint: 'По всем кампаниям',
    tone: 'neutral',
  },
  {
    label: 'Заказы',
    value: formatNumber(store.totalOrders),
    hint: 'Заказы из воронки за период',
    tone: 'success',
  },
  {
    label: 'Расходы на рекламу',
    value: formatCurrency(store.totalAdSpend),
    hint: 'Суммарные затраты кампаний',
    tone: 'danger',
  },
])

// Organic funnel conversions, precomputed by the backend from window totals.
const funnelConversions = computed(() => {
  const totals = product.value?.funnel_totals
  if (!totals) return []
  return [
    { label: 'Просмотр → корзина', value: totals.cart_conversion },
    { label: 'Корзина → заказ', value: totals.order_conversion },
    { label: 'Заказ → выкуп', value: totals.buyout_conversion },
  ]
})

function handleSearch({ sku, date_from, date_to }) {
  router.replace({ query: { sku, date_from, date_to } })
  store.fetchProductData(sku, { date_from, date_to })
}
</script>

<template>
  <div class="mx-auto w-full max-w-7xl space-y-6 px-4 py-8 sm:px-6 lg:px-8">
    <!-- Heading -->
    <header class="flex flex-wrap items-end justify-between gap-2">
      <div>
        <h1 class="text-2xl font-bold tracking-tight text-slate-900">Мониторинг SKU</h1>
        <p class="mt-1 text-sm text-slate-500">
          Воронка продаж, реклама и остатки по каждому SKU Wildberries.
        </p>
      </div>
      <p v-if="product" class="text-sm text-slate-400">
        Период <span class="font-medium text-slate-600">{{ windowLabel }}</span>
      </p>
    </header>

    <!-- Top layer: search & period filter -->
    <SkuSearchBar
      :loading="store.loading"
      :initial-query="initialSearch.sku"
      :initial-date-from="initialSearch.date_from"
      :initial-date-to="initialSearch.date_to"
      @search="handleSearch"
    />

    <!-- Ambiguous vendor-code search: let the user pick the exact SKU -->
    <section
      v-if="store.lookupMatches.length"
      class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
    >
      <p class="text-sm font-medium text-slate-900">
        Найдено артикулов: {{ store.lookupMatches.length }} — выберите нужный:
      </p>
      <div class="mt-3 flex flex-wrap gap-2">
        <button
          v-for="match in store.lookupMatches"
          :key="match.nm_id"
          type="button"
          class="inline-flex max-w-full items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm shadow-sm transition hover:border-indigo-600 hover:bg-indigo-50"
          @click="store.selectSku(match.nm_id)"
        >
          <span class="font-semibold text-slate-900">{{ match.vendor_code }}</span>
          <span class="truncate text-xs text-slate-400">{{ match.title }}</span>
        </button>
      </div>
    </section>

    <!-- Error state -->
    <div
      v-if="store.error"
      class="flex items-start gap-3 rounded-xl border border-rose-500/20 bg-rose-50 p-4 text-sm text-rose-500"
    >
      <span
        class="mt-0.5 flex h-5 w-5 flex-none items-center justify-center rounded-full bg-rose-500 text-xs font-bold text-white"
        >!</span
      >
      <div>
        <p class="font-semibold">Не удалось загрузить данные</p>
        <p class="mt-0.5">{{ store.error }}</p>
      </div>
    </div>

    <template v-if="product">
      <!-- Product identity -->
      <div class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 class="text-lg font-semibold text-slate-900">{{ product.title ?? skuLabel }}</h2>
        <span
          v-if="product.vendor_code"
          class="inline-flex items-center rounded-full bg-indigo-50 px-2.5 py-0.5 text-xs font-semibold text-indigo-600"
        >
          {{ product.vendor_code }}
        </span>
        <span class="text-sm text-slate-400">nm {{ product.nm_id }}</span>
      </div>

      <!-- Metric layer -->
      <section
        class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4"
        aria-label="Сводные метрики"
      >
        <MetricCard
          v-for="card in metricCards"
          :key="card.label"
          :label="card.label"
          :value="card.value"
          :hint="card.hint"
          :tone="card.tone"
        />
      </section>

      <!-- Funnel conversions strip -->
      <div
        class="flex flex-wrap items-center gap-x-6 gap-y-2 rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-sm"
      >
        <span class="text-sm font-medium text-slate-500">Конверсии воронки</span>
        <span
          v-for="conversion in funnelConversions"
          :key="conversion.label"
          class="flex items-baseline gap-1.5 text-sm text-slate-500"
        >
          {{ conversion.label }}
          <span class="font-semibold tabular-nums text-slate-900">
            {{ formatPercent(conversion.value) }}
          </span>
        </span>
      </div>

      <!-- OOS warning ribbon -->
      <div
        v-if="store.isOutOfStock"
        class="rounded-xl border border-amber-500/20 bg-amber-50 px-4 py-3 text-sm font-medium text-amber-600"
      >
        Товар сейчас отсутствует на складах — метрики спроса за этот период маскируются при
        нормализации.
      </div>

      <!-- Data layer: cross-attribution -->
      <section class="space-y-3">
        <div>
          <h2 class="text-base font-semibold text-slate-900">Кросс-атрибуция кампаний</h2>
          <p class="mt-0.5 text-sm text-slate-500">
            Кампании продвигают всю группу вариантов (все цвета); в каждой строке — заказы, которые
            кампания принесла именно артикулу {{ skuLabel }}.
          </p>
        </div>
        <CampaignAttributionTable :campaigns="product.advertising" :sku-label="skuLabel" />
      </section>

      <!-- Data layer: multi-size stock -->
      <section class="space-y-3">
        <div class="flex flex-wrap items-baseline justify-between gap-2">
          <div>
            <h2 class="text-base font-semibold text-slate-900">Остатки — размер × склад</h2>
            <p class="mt-0.5 text-sm text-slate-500">Остатки по каждому размеру на всех складах.</p>
          </div>
          <p class="text-sm text-slate-500">
            Всего
            <span class="font-semibold text-slate-900">
              {{ formatNumber(product.stock.total_quantity) }}
            </span>
            · к клиенту {{ formatNumber(product.stock.total_in_way_to_client) }} · возвраты
            {{ formatNumber(product.stock.total_in_way_from_client) }}
          </p>
        </div>
        <StockBreakdownTable :cells="product.stock.cells" :by-size="product.stock.by_size" />
      </section>
    </template>

    <!-- Empty state -->
    <section
      v-else-if="!store.loading && !store.error"
      class="flex flex-col items-center rounded-xl border border-dashed border-slate-200 bg-white px-6 py-16 text-center"
    >
      <span
        class="flex h-12 w-12 items-center justify-center rounded-xl bg-indigo-50 text-indigo-600"
      >
        <svg
          class="h-6 w-6"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.8"
          stroke-linecap="round"
        >
          <circle cx="11" cy="11" r="7" />
          <path d="m20 20-3.5-3.5" />
        </svg>
      </span>
      <h2 class="mt-4 text-base font-semibold text-slate-900">Начните с SKU</h2>
      <p class="mt-1 max-w-sm text-sm text-slate-500">
        Введите nm ID Wildberries, чтобы загрузить воронку продаж, атрибуцию кампаний и остатки по
        складам.
      </p>
    </section>
  </div>
</template>
