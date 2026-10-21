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

import PageHeader from '@/core/components/PageHeader.vue'
import BusyRegion from '@/core/components/BusyRegion.vue'
import DataState from '@/core/components/DataState.vue'

import PnlDashboardCards from '@/modules/finreports/components/PnlDashboardCards.vue'
import PnlPeriodControls from '@/modules/finreports/components/PnlPeriodControls.vue'
import ReportFreshnessLine from '@/modules/finreports/components/ReportFreshnessLine.vue'
import { providePnlCurrencies } from '@/modules/finreports/pnlFormat'
import { providePriceBase } from '@/modules/finreports/priceBase'
import { useFinReportsStore } from '@/modules/finreports/store'
import { useCostEntry } from '@/modules/finreports/useCostEntry'
import { useReportUpload } from '@/modules/finreports/useReportUpload'

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

// «Загрузить отчёт»: WB's weekly report, picked from the seller's disk.
const {
  busy: uploadBusy,
  notice: uploadNotice,
  error: uploadError,
  upload: uploadReport,
} = useReportUpload(store)
const reportFile = ref(null)
function pickReport(event) {
  const [file] = event.target.files ?? []
  // Cleared so picking the same file again still fires `change`.
  event.target.value = ''
  uploadReport(file)
}

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

// An uncosted article's cost, typed in the table — only for whoever may write.
const { save: saveCost } = useCostEntry(store)

// «Без себестоимости» over the table; the dashboard's counter turns it on and
// brings the table into view, so the counter leads to the very SKUs it counts.
const uncostedOnly = ref(false)
const skuSection = ref(null)
function showUncosted() {
  uncostedOnly.value = true
  skuSection.value?.scrollIntoView?.({ behavior: 'smooth', block: 'start' })
}

/** The harvested weeks have been asked for — until then «no reports» would be a guess. */
const weeksAsked = ref(Boolean(store.weeks.length))

onMounted(async () => {
  // Deliberately not awaited, and started first: the freshness line is a
  // footnote on the statement, so fetching it must not delay a single figure —
  // and if it fails, the line is simply absent.
  store.loadHarvestState()
  if (!store.weeks.length) await store.loadWeeks()
  weeksAsked.value = true
  if (!store.report) await store.loadReport()
})

watch(() => [store.dateFrom, store.dateTo], store.loadReport)
</script>

<template>
  <!-- `.app-container` is the shared canvas width + safe-area gutter (main.css). -->
  <div class="app-container py-lg">
    <PageHeader title="P&L" subtitle="По финансовым отчётам WB, построчно.">
      <template #actions>
        <!--
          The schedule asks WB hourly; this covers the hours it cannot — a report
          published overnight, or an hour the worker was down for.

          Disabled for one round trip and no longer: the click's job is to come
          back with an answer, not to sit on the page for the length of a
          harvest. It used to stay disabled until the run finished, which on a
          WB rate-limit block meant seven minutes of «Обновляем…» over a walk
          that was doing nothing but waiting.

          A secondary button beside a filled «Загрузить отчёт» on purpose — the
          same «Обновить» monitoring has: the hourly schedule makes a manual
          refresh rarely needed, and inside a WB block an extra press lengthens
          it. Two buttons, not three: «Себестоимость» lives on its own card,
          which says «Заполнить →» / «Изменить →» in so many words.
        -->
        <button
          type="button"
          :disabled="store.harvestBusy"
          class="ui-btn phone:flex-1"
          @click="store.refreshFromWb()"
        >
          {{ store.harvestBusy ? 'Обновляем…' : 'Обновить' }}
        </button>
        <!--
          The weekly report WB shows in the seller's account hours before its API serves
          it: the seller downloads it there and hands it over here. Hidden for a
          read-only member, whom the route would refuse.
        -->
        <template v-if="members.canWrite">
          <button
            type="button"
            :disabled="uploadBusy"
            class="ui-btn ui-btn--primary phone:flex-1"
            @click="reportFile?.click()"
          >
            {{ uploadBusy ? 'Загружаем…' : 'Загрузить отчёт' }}
          </button>
          <input
            ref="reportFile"
            type="file"
            accept=".zip,.xlsx"
            class="hidden"
            data-testid="report-file"
            @change="pickReport"
          />
        </template>
      </template>
    </PageHeader>

    <!--
      Why the statement stops where it does, on every load rather than only
      after «Обновить». WB publishes on no fixed day, so a P&L ending nine days
      ago is usually a quiet week and occasionally a dead harvester — and
      without this line the page shows the two identically.
    -->
    <ReportFreshnessLine :state="store.harvestState" class="mb-md" />

    <p v-if="uploadError" class="mb-md text-base text-status-negative">
      {{ uploadError }}
    </p>
    <p v-else-if="uploadNotice" class="mb-md text-base text-muted">
      {{ uploadNotice }}
    </p>

    <p v-if="store.harvestError" class="mb-md text-base text-status-negative">
      {{ store.harvestError }}
    </p>
    <p v-else-if="store.harvestNotice" class="mb-md text-base text-muted">
      {{ store.harvestNotice }}
    </p>

    <!-- Period: the shared calendar + presets -->
    <PnlPeriodControls v-model:price-base="priceBase" />

    <DataState v-if="!dashboard && (store.reportLoading || !weeksAsked)" kind="loading" />
    <DataState v-else-if="!dashboard && store.reportError" kind="error" :text="store.reportError" />
    <DataState
      v-else-if="!dashboard && !store.fullSpan"
      kind="empty"
      text="Отчётов WB пока нет"
      hint="Они появятся здесь сами, как только WB опубликует первый еженедельный отчёт."
    />

    <template v-else-if="dashboard">
      <DataState
        v-if="store.reportError"
        kind="error"
        layout="line"
        :text="store.reportError"
        class="mb-md"
      />
      <BusyRegion :busy="store.reportLoading">
        <PnlDashboardCards
          :dashboard="dashboard"
          :currency="currency"
          @show-uncosted="showUncosted"
        />

        <ul v-if="notes.length" class="mt-md space-y-xs">
          <li v-for="note in notes" :key="note" class="text-tiny text-muted">⚠ {{ note }}</li>
        </ul>

        <div ref="skuSection" class="mt-lg scroll-mt-md">
          <h2 class="mb-xs text-h3 font-semibold text-primary">По артикулам</h2>
          <p class="mb-sm max-w-4xl text-tiny text-muted">
            Продажи, возвраты и удержания — по датам расчёта WB.
          </p>
          <PnlSkuTable
            :rows="rows"
            :unallocated="unallocated"
            :base-dashboard="store.report?.dashboard ?? null"
            v-model:uncosted-only="uncostedOnly"
            :sizes="store.sizes"
            :currency="currency"
            :save-cost="members.canWrite ? saveCost : null"
            @toggle-exclusion="store.toggleExclusion($event.nmId, $event.excluded)"
            @dashboard-change="filteredDashboard = $event"
            @load-sizes="store.loadSizes($event)"
          />
        </div>
      </BusyRegion>

      <BalanceSection />
    </template>
  </div>
</template>
