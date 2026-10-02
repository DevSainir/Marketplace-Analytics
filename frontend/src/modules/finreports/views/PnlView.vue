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
import PnlPeriodControls from '@/modules/finreports/components/PnlPeriodControls.vue'
import ReportFreshnessLine from '@/modules/finreports/components/ReportFreshnessLine.vue'
import { providePnlCurrencies } from '@/modules/finreports/pnlFormat'
import { providePriceBase } from '@/modules/finreports/priceBase'
import { useFinReportsStore } from '@/modules/finreports/store'

import { useMembersStore } from '@/modules/profile'

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
const members = useMembersStore()

// The price every revenue figure on the page is shown at — a re-render, not a
// request: each row already carries both. See `priceBase.js`.
const priceBase = ref('seller')
providePriceBase(priceBase)

// The backend dashboard (exclusion-aware, whole window). While the table has a
// filter/search active it emits a «по фильтру» subtotal, which takes over —
// so the cards reflect only the SKUs on screen. `null` = no filter → backend.
const filteredDashboard = ref(null)
const dashboard = computed(() => filteredDashboard.value ?? store.report?.dashboard ?? null)
const rows = computed(() => store.report?.rows ?? [])
const unallocated = computed(() => store.report?.unallocated ?? null)
const notes = computed(() => store.report?.notes ?? [])
const currency = computed(() => store.report?.currency ?? '')
// Every figure on the page, advertising included, in the payout's currency.
providePnlCurrencies(computed(() => ({ settlement: currency.value })))

onMounted(async () => {
  // Deliberately not awaited, and started first: the freshness line is a
  // footnote on the statement, so fetching it must not delay a single figure —
  // and if it fails, the line is simply absent.
  store.loadHarvestState()
  if (!store.weeks.length) await store.loadWeeks()
  if (!store.report) await store.loadReport()
})

watch(() => [store.dateFrom, store.dateTo], store.loadReport)
</script>

<template>
  <!-- `.app-container` is the shared canvas width + safe-area gutter (main.css). -->
  <main class="app-container py-xl phone:py-lg">
    <header class="mb-lg flex flex-wrap items-end justify-between gap-md">
      <div>
        <h1 class="text-h2 font-bold text-primary">P&amp;L</h1>
        <p class="mt-xs max-w-3xl text-base text-muted">По финансовым отчётам WB, построчно.</p>
      </div>
      <div class="flex items-center gap-sm phone:w-full">
        <!--
          The schedule asks WB hourly; this covers the hours it cannot — a report
          published overnight, or an hour the worker was down for.

          Disabled for one round trip and no longer: the click's job is to come
          back with an answer, not to sit on the page for the length of a
          harvest. It used to stay disabled until the run finished, which on a
          WB rate-limit block meant seven minutes of «Обновляем…» over a walk
          that was doing nothing but waiting.

          A ghost button beside a filled «Себестоимость» on purpose: the hourly
          schedule makes a manual refresh rarely needed, and inside a WB block
          an extra press lengthens it. Filling in costs is the seller's own job.
        -->
        <button
          type="button"
          :disabled="store.harvestBusy"
          class="rounded-btn border border-border-strong/35 px-md py-sm text-base font-medium text-primary transition hover:border-border-strong/55 hover:bg-hover disabled:cursor-not-allowed disabled:text-muted disabled:hover:bg-transparent phone:min-h-11 phone:flex-1"
          @click="store.refreshFromWb()"
        >
          {{ store.harvestBusy ? 'Обновляем…' : 'Обновить' }}
        </button>
        <RouterLink
          :to="{ name: 'finreports-cost-prices' }"
          class="flex items-center justify-center rounded-btn bg-action px-lg py-sm text-base font-semibold text-white shadow-soft transition hover:bg-action-hover phone:min-h-11 phone:flex-1"
        >
          Себестоимость
        </RouterLink>
      </div>
    </header>

    <!--
      Why the statement stops where it does, on every load rather than only
      after «Обновить». WB publishes on no fixed day, so a P&L ending nine days
      ago is usually a quiet week and occasionally a dead harvester — and
      without this line the page shows the two identically.
    -->
    <ReportFreshnessLine :state="store.harvestState" class="mb-md" />

    <p v-if="store.harvestError" class="mb-md text-base text-status-negative">
      {{ store.harvestError }}
    </p>
    <p v-else-if="store.harvestNotice" class="mb-md text-base text-muted">
      {{ store.harvestNotice }}
    </p>

    <!-- Period: the shared calendar + presets -->
    <PnlPeriodControls v-model:price-base="priceBase" />

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
      <PnlDashboardCards
        :dashboard="dashboard"
        :currency="currency"
      />

      <ul v-if="notes.length" class="mt-md space-y-xs">
        <li v-for="note in notes" :key="note" class="text-tiny text-muted">⚠ {{ note }}</li>
      </ul>

      <div class="mt-lg">
        <h2 class="mb-xs text-h3 font-semibold text-primary">По артикулам</h2>
        <p class="mb-sm max-w-4xl text-tiny text-muted">
          Продажи, возвраты и удержания — по датам расчёта WB.
        </p>
        <PnlSkuTable
          :rows="rows"
          :unallocated="unallocated"
          :base-dashboard="store.report?.dashboard ?? null"
          :sizes="store.sizes"
          @toggle-exclusion="store.toggleExclusion($event.nmId, $event.excluded)"
          @dashboard-change="filteredDashboard = $event"
          @load-sizes="store.loadSizes($event)"
        />
      </div>

      <BalanceSection />
    </template>
  </main>
</template>
