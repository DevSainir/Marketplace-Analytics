<script setup>
/**
 * The finreports landing page: dashboard on top, per-SKU report below.
 *
 * Everything is computed from WB's weekly settlement detail plus the seller's
 * own cost prices, over an arbitrary date range — any start/end pair, not just
 * a report week, because the settlement rows are stored day-by-day. Two columns
 * come from other WB surfaces and say so in the caveats: «Заказы» from the
 * sales funnel and «Реклама» from the promotion statistics (the settlement
 * carries ad spend only as account-level invoices).
 */
import { computed, defineAsyncComponent, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'

import PnlDashboardCards from '@/modules/finreports/components/PnlDashboardCards.vue'
import { useFinReportsStore } from '@/modules/finreports/store'

import PeriodSelector from '@/core/components/PeriodSelector.vue'

/**
 * The SKU table pulls in PrimeVue's DataTable, which is ~400 kB — five times
 * the rest of this route. Loading it on demand keeps the dashboard (the four
 * figures a seller opens this page for) painting immediately.
 */
const PnlSkuTable = defineAsyncComponent(
  () => import('@/modules/finreports/components/PnlSkuTable.vue'),
)

/**
 * The stock balance is the page's third block and the heaviest grid on it
 * (every SKU x every warehouse). Loaded on demand for the same reason as the
 * SKU table, so the dashboard still paints first.
 */
const BalanceSection = defineAsyncComponent(
  () => import('@/modules/finreports/components/BalanceSection.vue'),
)

const store = useFinReportsStore()

const PRESETS = [
  { key: 7, label: '7 дней' },
  { key: 30, label: '30 дней' },
  { key: 90, label: '90 дней' },
]

// The backend dashboard (exclusion-aware, whole window). While the table has a
// filter/search active it emits a «по фильтру» subtotal, which takes over —
// so the cards reflect only the SKUs on screen. `null` = no filter → backend.
const filteredDashboard = ref(null)
const dashboard = computed(() => filteredDashboard.value ?? store.report?.dashboard ?? null)
const rows = computed(() => store.report?.rows ?? [])
const unallocated = computed(() => store.report?.unallocated ?? null)
const notes = computed(() => store.report?.notes ?? [])
const currency = computed(() => store.report?.currency ?? '')

const isAllHistory = computed(
  () =>
    store.fullSpan &&
    store.dateFrom === store.fullSpan.date_from &&
    store.dateTo === store.fullSpan.date_to,
)

function isPresetActive(days) {
  if (!store.fullSpan || isAllHistory.value) return false
  const end = store.fullSpan.date_to
  if (store.dateTo !== end) return false
  const start = new Date(new Date(end).getTime() - (days - 1) * 86400000)
  return store.dateFrom === start.toISOString().slice(0, 10)
}

onMounted(async () => {
  if (!store.weeks.length) await store.loadWeeks()
  if (!store.report) await store.loadReport()
})

watch(() => [store.dateFrom, store.dateTo], store.loadReport)
</script>

<template>
  <main class="mx-auto w-full max-w-[calc(26.667rem_+_66.667vw)] px-md py-xl sm:px-lg">
    <header class="mb-lg flex flex-wrap items-end justify-between gap-md">
      <div>
        <h1 class="text-h2 font-bold text-primary">Прибыли и убытки</h1>
        <p class="mt-xs max-w-3xl text-base text-muted">
          По еженедельной детализации финансовых отчётов WB, построчно. Отчёт по артикулам — только
          из строк самого артикула; общие удержания счёта показаны отдельной строкой.
        </p>
      </div>
      <div class="flex items-center gap-sm">
        <!--
          The schedule asks WB hourly; this covers the hours it cannot — a report
          published overnight, or an hour the worker was down for. Disabled while
          a harvest runs: the backend refuses a second one anyway, and a button
          that looks clickable but changes nothing reads as broken.
        -->
        <button
          type="button"
          :disabled="store.harvestRunning"
          class="rounded-btn border border-border-subtle bg-surface px-md py-sm text-base font-medium text-primary transition hover:border-action hover:text-action disabled:cursor-not-allowed disabled:text-muted disabled:hover:border-border-subtle disabled:hover:text-muted"
          @click="store.refreshFromWb()"
        >
          {{ store.harvestRunning ? 'Обновляем…' : 'Обновить' }}
        </button>
        <RouterLink
          :to="{ name: 'finreports-cost-prices' }"
          class="rounded-btn border border-border-subtle bg-surface px-md py-sm text-base font-medium text-primary transition hover:border-action hover:text-action"
        >
          Себестоимость
        </RouterLink>
      </div>
    </header>

    <p v-if="store.harvestError" class="mb-md text-base text-status-negative">
      {{ store.harvestError }}
    </p>
    <p v-else-if="store.harvestNotice" class="mb-md text-base text-muted">
      {{ store.harvestNotice }}
    </p>

    <!-- Period: the shared calendar + presets -->
    <div class="mb-lg flex flex-wrap items-center gap-md">
      <PeriodSelector
        :from="store.dateFrom"
        :to="store.dateTo"
        :preset-end="store.fullSpan?.date_to ?? ''"
        @update:from="store.setPeriod($event, store.dateTo)"
        @update:to="store.setPeriod(store.dateFrom, $event)"
      />

      <div class="flex items-center gap-xs rounded-btn border border-border-subtle bg-surface p-xs">
        <button
          v-for="preset in PRESETS"
          :key="preset.key"
          type="button"
          class="rounded-btn px-md py-xs text-base font-medium transition"
          :class="
            isPresetActive(preset.key)
              ? 'bg-action text-white'
              : 'text-muted hover:bg-hover hover:text-primary'
          "
          @click="store.setPresetDays(preset.key)"
        >
          {{ preset.label }}
        </button>
        <button
          type="button"
          class="rounded-btn px-md py-xs text-base font-medium transition"
          :class="
            isAllHistory ? 'bg-action text-white' : 'text-muted hover:bg-hover hover:text-primary'
          "
          @click="store.setPresetAll()"
        >
          Вся история
        </button>
      </div>
    </div>

    <div
      v-if="store.reportLoading"
      class="rounded-card border border-border-subtle bg-surface px-lg py-xl text-center text-base text-muted shadow-card"
    >
      Считаем отчёт…
    </div>

    <div
      v-else-if="store.reportError"
      class="rounded-card border border-border-subtle bg-surface px-lg py-xl text-center shadow-card"
    >
      <p class="font-semibold text-primary">Отчёт недоступен</p>
      <p class="mt-xs text-base text-muted">{{ store.reportError }}</p>
    </div>

    <template v-else-if="dashboard">
      <PnlDashboardCards :dashboard="dashboard" :currency="currency" />

      <ul v-if="notes.length" class="mt-md space-y-xs">
        <li v-for="note in notes" :key="note" class="text-tiny text-muted">⚠ {{ note }}</li>
      </ul>

      <div class="mt-lg">
        <h2 class="mb-xs text-h3 font-semibold text-primary">По артикулам</h2>
        <p class="mb-sm max-w-4xl text-tiny text-muted">
          Продажи, возвраты и удержания — по датам расчёта WB: строки его же еженедельного отчёта,
          сумма сходится с «Итого к оплате» до копейки. Сервисы, считающие «продажи» по когортам
          заказов периода, за свежие даты покажут меньшие числа — большая часть заказов ещё не
          выкуплена и в расчёт WB не попала.
        </p>
        <PnlSkuTable
          :rows="rows"
          :unallocated="unallocated"
          :base-dashboard="store.report?.dashboard ?? null"
          :currency="currency"
          @toggle-exclusion="store.toggleExclusion($event.nmId, $event.excluded)"
          @dashboard-change="filteredDashboard = $event"
        />
      </div>

      <BalanceSection />
    </template>
  </main>
</template>
